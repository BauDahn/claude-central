#!/usr/bin/env python3
"""Dictado por voz (Whisper local) -> escribe el texto en la ventana activa.

Un atajo (toggle): la primera pulsacion empieza a grabar; termina solo tras
un silencio, o con una segunda pulsacion. Luego transcribe y escribe el
texto con wtype (sin Enter: lo revisas y lo mandas vos).

Variables: DICTATE_LANG (def es, vacio = autodetectar), DICTATE_MODEL (def small),
           DICTATE_SILENCE (segundos de silencio para cortar, def 1.3).
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import voice  # noqa: E402

PIDFILE = BASE / "recording.pid"
LANGUAGE = os.environ.get("DICTATE_LANG", "es") or None
MODEL = os.environ.get("DICTATE_MODEL", "small")
SILENCE = float(os.environ.get("DICTATE_SILENCE", "1.3"))
MAX_SECONDS = 90
NO_SPEECH_SECONDS = 10
DUCK = float(os.environ.get("DICTATE_DUCK", "0.4"))  # 0.4 = al 40% del volumen actual

finish = False


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def notify(msg, ms=2500):
    subprocess.run(
        ["notify-send", "-a", "Dictado", "-t", str(ms),
         "-h", "string:x-canonical-private-synchronous:dictado", msg],
        check=False,
    )


def on_usr1(*_):
    global finish
    finish = True


def record():
    import numpy as np

    p = subprocess.Popen(
        ["parecord", *voice.mic_args(), "--raw", "--format=s16le", "--rate=16000",
         "--channels=1", "--latency-msec=30"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    chunk = 960  # 30 ms
    frames, noise, thr = [], [], None
    spoke, start = False, time.monotonic()
    last_voice = start
    try:
        while not finish:
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
            if spoke and now - last_voice > SILENCE:
                break
            if not spoke and now - start > NO_SPEECH_SECONDS:
                break
            if now - start > MAX_SECONDS:
                break
    finally:
        p.terminate()
    if not spoke and not finish:
        return None
    return np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(audio):
    from faster_whisper import WhisperModel

    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=8)
    segments, _ = model.transcribe(
        audio, language=LANGUAGE, beam_size=5, vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()


def hypr_json(*args):
    try:
        out = subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True, timeout=3).stdout
        return json.loads(out)
    except Exception:
        return None


def hypr_focus(address):
    subprocess.run(["hyprctl", "dispatch", "focuswindow", f"address:{address}"],
                   stdout=subprocess.DEVNULL, check=False)


def claude_target(name=None):
    """Ventana de la terminal de Claude a la que va el dictado (o None).

    Usa el destino elegido por voz (names.current()); si esa ventana ya no
    existe, cae a la central y luego a la usada mas recientemente."""
    import names
    clients = hypr_json("clients") or []
    registered = {int(p.name) for p in voice.SESSIONS.glob("*") if p.name.isdigit()}
    cands = [c for c in clients if c.get("pid") in registered and c.get("mapped", True)]
    for nm in (name or names.current(), names.CENTRAL):
        pid = names.pid_for(nm)
        mine = [c for c in cands if c.get("pid") == pid]
        if mine:
            return mine[0]
    return min(cands, key=lambda c: c.get("focusHistoryID", 99)) if cands else None


def send_return(target=None):
    """Pulsa Enter en la terminal de Claude sin darle el foco."""
    t = target or claude_target()
    if t is None:
        subprocess.run(["notify-send", "-a", "Escucha", "No hay sesión de Claude abierta"], check=False)
        return False
    subprocess.run(["hyprctl", "dispatch", "sendshortcut", f", Return, address:{t['address']}"],
                   stdout=subprocess.DEVNULL, check=False)
    return True


def type_text(text, enter=False, target_name=None):
    if shutil.which("wtype"):
        def args_run(_=None):
            subprocess.run(["wtype", "--", text], check=False)
            if enter:
                subprocess.run(["wtype", "-k", "Return"], check=False)
        target = claude_target(target_name)
        active = hypr_json("activewindow") or {}
        if target and target["address"] != active.get("address"):
            # Cambiar el foco a la terminal de Claude, escribir y volver
            hypr_focus(target["address"])
            time.sleep(0.25)
            args_run()
            time.sleep(0.1)
            if active.get("address"):
                hypr_focus(active["address"])
        else:
            args_run()
        return
    # Fallback sin wtype: portapapeles + Ctrl+Shift+V (terminal kitty)
    old = subprocess.run(["wl-paste", "-n"], capture_output=True).stdout
    subprocess.run(["wl-copy", "--", text], check=False)
    time.sleep(0.1)
    subprocess.run(["hyprctl", "dispatch", "sendshortcut", "CTRL SHIFT, V, activewindow"],
                   stdout=subprocess.DEVNULL, check=False)
    time.sleep(0.4)
    subprocess.run(["wl-copy", "--"], input=old, check=False)


def main():
    if PIDFILE.exists():
        try:
            pid = int(PIDFILE.read_text())
        except ValueError:
            pid = 0
        if pid and alive(pid):
            os.kill(pid, signal.SIGUSR1)  # segunda pulsacion: terminar
            return
    PIDFILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGUSR1, on_usr1)
    try:
        voice.stop_current()  # callar a Claude mientras hablas
        voice.duck_volumes(DUCK)  # bajar la musica mientras hablas
        notify("🎙 Escuchando…", 1500)
        try:
            audio = record()
        finally:
            voice.restore_volumes()  # subirla en cuanto terminas de hablar
        if audio is None or len(audio) < 8000:
            notify("No te escuché nada")
            return
        notify("⏳ Transcribiendo…", 1500)
        text = transcribe(audio)
        if not text:
            notify("No entendí lo que dijiste")
            return
        type_text(text)
        notify("✍ " + text, 3000)
    except Exception as e:
        notify(f"Error de dictado: {e}", 6000)
        (BASE / "error.log").write_text(repr(e) + "\n")
    finally:
        PIDFILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
