#!/usr/bin/env python3
"""Worker local de voz para Station: Kokoro ONNX (TTS) + Silero VAD + faster-whisper (STT).

Puede correr en el Python actual o en el venv de voz (~/.local/share/claude-voice/venv)
mediante RPC por stdin/stdout en líneas JSON (`--rpc`) o en modo directo (`--oneshot`).
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

# Permite importar agent_station.voz.motor aunque este script corra en un venv externo.
_SRC_ROOT = str(Path(__file__).resolve().parents[2])
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from agent_station.voz import motor  # noqa: E402

CHUNK_VAD = 512      # 32 ms a 16 kHz (Silero VAD)
CHUNK_RMS = 480      # 30 ms a 16 kHz (samples)
PRE_ROLL = 0.3
MIN_SPEECH = 0.4
SHORT_SPEECH = 0.2
MAX_UTTERANCE = 60.0


def _emit(obj: dict):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _load_kokoro():
    from kokoro_onnx import Kokoro
    onnx, voices = motor.modelos_kokoro()
    if not onnx or not voices:
        raise FileNotFoundError("No encontré los modelos locales de Kokoro (kokoro-v1.0.onnx / voices-v1.0.bin).")
    return Kokoro(str(onnx), str(voices))


def _load_whisper(model_name: str):
    from faster_whisper import WhisperModel
    device = os.environ.get("STATION_VOICE_DEVICE", "cuda")
    if device != "cpu":
        try:
            import ctypes
            import glob
            import site
            for d in site.getsitepackages():
                for f in glob.glob(d + "/nvidia/cublas/lib/libcublas*.so.12"):
                    ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
            return WhisperModel(model_name, device="cuda", compute_type="int8_float16")
        except Exception:
            pass
    return WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=8)


class _SileroVad:
    def __init__(self):
        import faster_whisper
        from faster_whisper.vad import SileroVADModel
        import numpy as np

        self._np = np
        path = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
        self.m = SileroVADModel(str(path))
        self.reset()

    def reset(self):
        np = self._np
        self.h = np.zeros((1, 1, 128), dtype="float32")
        self.c = np.zeros((1, 1, 128), dtype="float32")
        self.ctx = np.zeros((1, 64), dtype="float32")

    def prob(self, x):
        np = self._np
        inp = np.concatenate([self.ctx, x.reshape(1, -1)], axis=1)
        out, self.h, self.c = self.m.session.run(None, {"input": inp, "h": self.h, "c": self.c})
        self.ctx = x.reshape(1, -1)[:, -64:]
        return float(np.asarray(out).ravel()[0])


class VoiceWorker:
    def __init__(self):
        self.cfg = {
            "voice": "af_heart",
            "speed": 1.05,
            "lang_tts": "en-us",
            "lang_stt": "es",
            "model_stt": "small",
            "barge_in": True,
            "ducking": True,
            "duck_factor": 0.3,
            "silence_dictate": 1.3,
            "silence_listen": 0.9,
            "threshold": 0.5,
        }
        self._kokoro = None
        self._whisper = None
        self._whisper_name = None
        self._vad = None
        self._model_lock = threading.Lock()

        # TTS state
        self._tts_lock = threading.Lock()
        self._tts_stop_ev = threading.Event()
        self._tts_thread: threading.Thread | None = None
        self._tts_proc: subprocess.Popen | None = None
        self._tts_playing = False
        self._tts_gen = 0

        # Dictate state
        self._dictate_active = False
        self._dictate_stop_ev = threading.Event()
        self._dictate_target = "chat"

        # Continuous listen state
        self._listen_active = False
        self._listen_paused = False
        self._listen_stop_ev = threading.Event()
        self._listen_thread: threading.Thread | None = None
        self._transcribe_q: queue.Queue = queue.Queue()
        self._transcriber_started = False
        self._transcribing = False
        self._state = "idle"
        self._mute_until = 0.0

    def _set_state(self, state: str):
        if state != self._state:
            self._state = state
            _emit({"event": "state", "state": state})

    def _get_kokoro(self):
        with self._model_lock:
            if self._kokoro is None:
                self._kokoro = _load_kokoro()
            return self._kokoro

    def _get_whisper(self):
        name = self.cfg.get("model_stt") or "small"
        with self._model_lock:
            if self._whisper is None or self._whisper_name != name:
                self._whisper = _load_whisper(name)
                self._whisper_name = name
            return self._whisper

    def _get_vad(self):
        with self._model_lock:
            if self._vad is None:
                self._vad = _SileroVad()
            return self._vad

    # ------------------------------------------------------------------ TTS
    def stop_tts(self):
        with self._tts_lock:
            self._tts_gen += 1
            self._tts_stop_ev.set()
            proc = self._tts_proc
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
            t = self._tts_thread
        if t and t.is_alive() and threading.current_thread() is not t:
            t.join(timeout=1.5)
        if self.cfg.get("ducking", True):
            motor.restore_volumes()

    def speak(self, text: str, speak_id: str = "", force: bool = False):
        clean = motor.limpiar_para_tts(text)
        if not clean:
            return
        lang_tts = self.cfg.get("lang_tts") or "en-us"
        if not force and lang_tts.startswith("en") and motor.tiene_espanol(clean):
            _emit({"event": "tts_skipped", "id": speak_id, "reason": "spanish_chars"})
            return
        self.stop_tts()
        with self._tts_lock:
            self._tts_stop_ev.clear()
            gen = self._tts_gen
            t = threading.Thread(
                target=self._run_tts,
                args=(clean, speak_id, gen, lang_tts),
                daemon=True,
            )
            self._tts_thread = t
            t.start()

    def _barge_in_watcher(self, stop_ev: threading.Event):
        import numpy as np
        p = subprocess.Popen(
            ["parecord", *motor.mic_args(), "--raw", "--format=s16le", "--rate=16000",
             "--channels=1", "--latency-msec=30"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        chunk = CHUNK_RMS * 2
        noise, thr, hot = [], None, 0
        try:
            while not stop_ev.is_set():
                data = p.stdout.read(chunk)
                if not data or len(data) < chunk:
                    break
                x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(x * x)))
                if thr is None:
                    noise.append(rms)
                    if len(noise) >= 15:
                        floor = float(np.percentile(noise, 20))
                        thr = min(max(floor * 4, 300.0), 1200.0)
                    continue
                hot = hot + 1 if rms > thr else 0
                if hot >= 8:
                    _emit({"event": "barge_in"})
                    stop_ev.set()
                    proc = self._tts_proc
                    if proc and proc.poll() is None:
                        try:
                            proc.terminate()
                        except OSError:
                            pass
                    return
        finally:
            try:
                p.terminate()
                p.wait(timeout=1)
            except Exception:
                pass

    def _run_tts(self, text: str, speak_id: str, gen: int, lang_tts: str):
        import soundfile as sf
        tmpdir = tempfile.mkdtemp(prefix="st-voice-")
        ducked = False
        barge_stop = threading.Event()
        try:
            kokoro = self._get_kokoro()
            if self._tts_stop_ev.is_set() or gen != self._tts_gen:
                return
            self._tts_playing = True
            _emit({"event": "tts_start", "id": speak_id})
            if not self._listen_active:
                self._set_state("talking")

            if (
                self.cfg.get("barge_in", True)
                and not self._listen_active
                and not motor.bt_headset()
            ):
                threading.Thread(target=self._barge_in_watcher, args=(barge_stop,), daemon=True).start()

            q: queue.Queue = queue.Queue(maxsize=2)
            voice_name = self.cfg.get("voice") or "af_heart"
            speed = float(self.cfg.get("speed") or 1.05)

            def producer():
                try:
                    for n, s in enumerate(motor.dividir_frases(text)):
                        if self._tts_stop_ev.is_set() or barge_stop.is_set() or gen != self._tts_gen:
                            break
                        samples, sr = kokoro.create(s, voice=voice_name, speed=speed, lang=lang_tts)
                        p = os.path.join(tmpdir, f"{n}.wav")
                        sf.write(p, samples, sr)
                        q.put(p)
                except Exception as exc:
                    _emit({"event": "error", "message": f"Error en TTS: {exc}"})
                finally:
                    q.put(None)

            threading.Thread(target=producer, daemon=True).start()
            while True:
                p = q.get()
                if p is None:
                    break
                if self._tts_stop_ev.is_set() or barge_stop.is_set() or gen != self._tts_gen:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
                    continue
                if not ducked and self.cfg.get("ducking", True):
                    motor.duck_volumes(float(self.cfg.get("duck_factor", 0.3)))
                    ducked = True
                proc = subprocess.Popen(motor.paplay_cmd(p), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._tts_proc = proc
                while proc.poll() is None:
                    if self._tts_stop_ev.is_set() or barge_stop.is_set() or gen != self._tts_gen:
                        proc.terminate()
                        break
                    time.sleep(0.03)
                proc.wait()
                self._tts_proc = None
                try:
                    os.unlink(p)
                except OSError:
                    pass
        except Exception as exc:
            _emit({"event": "error", "message": f"No se pudo hablar: {exc}"})
        finally:
            barge_stop.set()
            self._tts_playing = False
            self._mute_until = time.monotonic() + 0.35
            if ducked:
                motor.restore_volumes()
            shutil.rmtree(tmpdir, ignore_errors=True)
            _emit({"event": "tts_end", "id": speak_id})
            if not self._listen_active and not self._dictate_active:
                self._set_state("idle")

    # -------------------------------------------------------------- Dictate
    def dictate_start(self, target: str = "chat"):
        if self._dictate_active:
            return
        self.stop_tts()
        self._dictate_active = True
        self._dictate_stop_ev.clear()
        self._dictate_target = target
        threading.Thread(target=self._run_dictate, args=(target,), daemon=True).start()

    def dictate_stop(self):
        self._dictate_stop_ev.set()

    def _run_dictate(self, target: str):
        import numpy as np
        ducked = False
        was_listening = self._listen_active and not self._listen_paused
        if was_listening:
            self._listen_paused = True
            time.sleep(0.15)
        try:
            if self.cfg.get("ducking", True):
                motor.duck_volumes(0.4)
                ducked = True
            self._set_state("hearing")
            p = subprocess.Popen(
                ["parecord", *motor.mic_args(), "--raw", "--format=s16le", "--rate=16000",
                 "--channels=1", "--latency-msec=30"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            chunk = CHUNK_RMS * 2
            frames, noise, thr = [], [], None
            spoke, start = False, time.monotonic()
            last_voice = start
            silence_s = float(self.cfg.get("silence_dictate", 1.3))
            try:
                while not self._dictate_stop_ev.is_set():
                    data = p.stdout.read(chunk)
                    if not data or len(data) < chunk:
                        break
                    frames.append(data)
                    x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    rms = float(np.sqrt(np.mean(x * x)))
                    if thr is None:
                        noise.append(rms)
                        if len(noise) >= 15:
                            thr = min(max(float(np.percentile(noise, 20)) * 4, 300.0), 1200.0)
                        continue
                    now = time.monotonic()
                    if rms > thr:
                        spoke, last_voice = True, now
                    if spoke and now - last_voice > silence_s:
                        break
                    if not spoke and now - start > 10.0:
                        break
                    if now - start > 90.0:
                        break
            finally:
                p.terminate()
                p.wait(timeout=1)

            if ducked:
                motor.restore_volumes()
                ducked = False

            if not spoke and not self._dictate_stop_ev.is_set():
                _emit({"event": "dictate_result", "target": target, "text": "", "reason": "no_speech"})
                return
            audio = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0
            if len(audio) < 6000:
                _emit({"event": "dictate_result", "target": target, "text": "", "reason": "too_short"})
                return
            self._set_state("transcribing")
            t0 = time.monotonic()
            text = self._transcribe(audio)
            dt = time.monotonic() - t0
            _emit({"event": "dictate_result", "target": target, "text": text, "dt": round(dt, 2)})
        except Exception as exc:
            _emit({"event": "error", "message": f"Error en dictado: {exc}"})
            _emit({"event": "dictate_result", "target": target, "text": "", "reason": "error"})
        finally:
            if ducked:
                motor.restore_volumes()
            self._dictate_active = False
            if was_listening:
                self._listen_paused = False
            if not self._listen_active:
                self._set_state("idle")

    def _transcribe(self, audio) -> str:
        model = self._get_whisper()
        lang = self.cfg.get("lang_stt") or None
        prompt = motor.RIOPLATENSE_PROMPT if lang == "es" else None
        segs, _ = model.transcribe(
            audio,
            language=lang,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        text = " ".join(s.text.strip() for s in segs).strip()
        if lang == "es":
            text = motor.fix_rioplatense(text)
        return text

    # ------------------------------------------------------- Continuous listen
    def _ensure_transcriber(self):
        if self._transcriber_started:
            return
        self._transcriber_started = True
        threading.Thread(target=self._transcriber_loop, daemon=True).start()

    def _transcriber_loop(self):
        while True:
            audio, short = self._transcribe_q.get()
            self._transcribing = True
            try:
                t0 = time.monotonic()
                text = self._transcribe(audio)
                dt = time.monotonic() - t0
                low = text.lower().strip()
                if len(low) < 2 or low in motor.HALLUCINATIONS:
                    continue
                if short and motor.match_command(text) is None:
                    continue
                _emit({"event": "heard", "text": text, "short": short, "dt": round(dt, 2)})
            except Exception as exc:
                _emit({"event": "error", "message": f"Error transcribiendo: {exc}"})
            finally:
                self._transcribing = False

    def listen_start(self):
        if self._listen_active:
            self._listen_paused = False
            return
        self._ensure_transcriber()
        self._listen_active = True
        self._listen_paused = False
        self._listen_stop_ev.clear()
        self._listen_thread = threading.Thread(target=self._run_listen, daemon=True)
        self._listen_thread.start()

    def listen_stop(self):
        self._listen_active = False
        self._listen_stop_ev.set()
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=1.5)
        if not self._dictate_active and not self._tts_playing:
            self._set_state("idle")

    def listen_pause(self, paused: bool):
        self._listen_paused = bool(paused)
        if self._listen_paused:
            self._set_state("paused")

    def _run_listen(self):
        import numpy as np
        self._set_state("loading")
        try:
            self._get_whisper()
            vad = self._get_vad()
        except Exception as exc:
            self._listen_active = False
            _emit({"event": "error", "message": f"No se pudo cargar voz local: {exc}"})
            self._set_state("error")
            return

        def open_mic():
            return subprocess.Popen(
                ["parecord", *motor.mic_args(), "--raw", "--format=s16le", "--rate=16000",
                 "--channels=1", "--latency-msec=30"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )

        p = None
        pre = deque(maxlen=int(PRE_ROLL * 16000 / CHUNK_VAD))
        frames, speaking, voiced, last_voice, hot = [], False, 0, 0.0, 0
        thr = float(self.cfg.get("threshold", 0.5))
        silence_s = float(self.cfg.get("silence_listen", 0.9))
        ducked = False
        barge_hot = 0

        try:
            while not self._listen_stop_ev.is_set() and self._listen_active:
                if self._listen_paused:
                    if p is not None:
                        if ducked:
                            motor.restore_volumes(fade=0.3)
                            ducked = False
                        p.terminate()
                        p.wait(timeout=1)
                        p = None
                        frames, speaking, voiced, hot, barge_hot = [], False, 0, 0, 0
                        vad.reset()
                        pre.clear()
                    self._set_state("paused")
                    time.sleep(0.08)
                    continue

                if p is None:
                    p = open_mic()
                    self._set_state("listening")

                data = p.stdout.read(CHUNK_VAD * 2)
                if not data or len(data) < CHUNK_VAD * 2:
                    if self._listen_paused or self._listen_stop_ev.is_set():
                        continue
                    break

                x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                talking = self._tts_playing
                self._set_state(
                    "paused" if self._listen_paused else
                    "talking" if talking else
                    "hearing" if speaking else
                    "transcribing" if self._transcribing else
                    "listening"
                )

                if talking or time.monotonic() < self._mute_until:
                    # Barge-in con el mismo micrófono abierto si está habilitado
                    if talking and self.cfg.get("barge_in", True):
                        pr = vad.prob(x)
                        barge_hot = barge_hot + 1 if pr > max(thr, 0.6) else 0
                        if barge_hot >= 7:  # ~224 ms de voz sostenida
                            barge_hot = 0
                            _emit({"event": "barge_in"})
                            self.stop_tts()
                            speaking, frames, voiced, last_voice = True, list(pre), 0, time.monotonic()
                            continue
                    if speaking or hot:
                        if ducked and not talking:
                            motor.restore_volumes(fade=0.3)
                            ducked = False
                        frames, speaking, voiced, hot = [], False, 0, 0
                        vad.reset()
                    pre.append(x)
                    continue

                barge_hot = 0
                pr = vad.prob(x)
                now = time.monotonic()
                if not speaking:
                    pre.append(x)
                    hot = hot + 1 if pr > thr else 0
                    if hot >= 3:
                        speaking, frames, voiced, last_voice = True, list(pre), 0, now
                        if self.cfg.get("ducking", True) and not ducked:
                            ducked = True
                            threading.Thread(target=lambda: motor.duck_volumes(0.25, fade=0.2), daemon=True).start()
                else:
                    frames.append(x)
                    if pr > thr - 0.15:
                        last_voice = now
                    if pr > thr:
                        voiced += 1
                    done = now - last_voice > silence_s or len(frames) * CHUNK_VAD / 16000 > MAX_UTTERANCE
                    if done:
                        v = voiced * CHUNK_VAD / 16000
                        if v >= SHORT_SPEECH:
                            self._transcribe_q.put((np.concatenate(frames), v < MIN_SPEECH))
                        frames, speaking, voiced, hot = [], False, 0, 0
                        pre.clear()
                        vad.reset()
                        if ducked:
                            ducked = False
                            threading.Thread(target=lambda: motor.restore_volumes(fade=0.4), daemon=True).start()
        finally:
            if p is not None:
                try:
                    p.terminate()
                    p.wait(timeout=1)
                except Exception:
                    pass
            if ducked:
                motor.restore_volumes()

    # -------------------------------------------------------------- RPC Loop
    def serve_rpc(self):
        _emit({"event": "ready"})
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            cmd = msg.get("cmd")
            if cmd == "config":
                for k, v in msg.items():
                    if k != "cmd":
                        self.cfg[k] = v
            elif cmd == "speak":
                self.speak(msg.get("text", ""), msg.get("id", ""), force=bool(msg.get("force", False)))
            elif cmd == "stop_tts":
                self.stop_tts()
            elif cmd == "dictate_start":
                self.dictate_start(msg.get("target", "chat"))
            elif cmd == "dictate_stop":
                self.dictate_stop()
            elif cmd == "listen_start":
                self.listen_start()
            elif cmd == "listen_stop":
                self.listen_stop()
            elif cmd == "listen_pause":
                self.listen_pause(bool(msg.get("paused", True)))
            elif cmd == "quit":
                self.listen_stop()
                self.stop_tts()
                break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", action="store_true")
    ap.add_argument("--oneshot", choices=["speak", "dictate"])
    ap.add_argument("--text", default="")
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--speed", type=float, default=1.05)
    ap.add_argument("--lang", default="en-us")
    ap.add_argument("--lang-stt", default="es")
    ap.add_argument("--model-stt", default="small")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    w = VoiceWorker()
    w.cfg["voice"] = a.voice
    w.cfg["speed"] = a.speed
    w.cfg["lang_tts"] = a.lang
    w.cfg["lang_stt"] = a.lang_stt
    w.cfg["model_stt"] = a.model_stt

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    if a.rpc:
        w.serve_rpc()
        return
    if a.oneshot == "speak":
        w.speak(a.text, force=a.force)
        if w._tts_thread:
            w._tts_thread.join()
    elif a.oneshot == "dictate":
        w.dictate_start("cli")
        while w._dictate_active:
            time.sleep(0.05)


if __name__ == "__main__":
    main()
