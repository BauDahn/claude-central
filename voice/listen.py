#!/usr/bin/env python3
"""Escucha continua: VAD (Silero) + Whisper local -> escribe en la terminal de Claude.

Siempre escucha el microfono. Cuando detecta que hablas y haces una pausa,
transcribe y manda el texto a Claude (con Enter). Se calla mientras Claude
habla (para no oirse a si mismo); la voz ya se corta sola si la interrumpes.

Uso:
  listen.py              -> arranca el demonio (Ctrl+C para salir)
  listen.py toggle       -> pausa / reanuda (manda SIGUSR1 al demonio)
  listen.py --dry        -> solo muestra lo que oye, sin escribir nada

Variables: LISTEN_SEND (1 = pulsa Enter solo, 0 = solo escribe; def 0),
           LISTEN_MODEL (def small), LISTEN_LANG (def es),
           LISTEN_SILENCE (s de pausa para cortar, def 0.9),
           LISTEN_THRESHOLD (prob. de voz, def 0.5).
"""
import os
import re
import signal
import subprocess
import sys
import threading
import queue
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import numpy as np  # noqa: E402
import voice  # noqa: E402

PID = BASE / "listen.pid"
SEND = os.environ.get("LISTEN_SEND", "0") == "1"   # def: NO enviar solo; Enter con boton del raton
MODEL = os.environ.get("LISTEN_MODEL", "small")
DEVICE = os.environ.get("LISTEN_DEVICE", "cuda")
LANG = os.environ.get("LISTEN_LANG", "es") or None
SILENCE = float(os.environ.get("LISTEN_SILENCE", "0.9"))
THR = float(os.environ.get("LISTEN_THRESHOLD", "0.5"))
MIN_SPEECH = 0.4          # s minimos de voz para considerarlo una frase
SHORT_SPEECH = 0.2        # entre 0.2 y 0.4 s: solo vale si Whisper devuelve una palabra de comando
PRE_ROLL = 0.3            # s de audio previo que se conserva
MAX_UTTERANCE = 60.0
CHUNK = 512               # 32 ms a 16 kHz
DRY = "--dry" in sys.argv

# Alucinaciones tipicas de Whisper con ruido/silencio
HALLUCINATIONS = {
    "gracias", "gracias.", "gracias por ver el video", "gracias por ver el video.",
    "subtítulos realizados por la comunidad de amara.org", "suscríbete", "...",
    "thank you", "thank you.", "you", "bye", "bye.",
}

paused = False
busy = 0
BUSY = BASE / "busy"
WAIT = os.environ.get("LISTEN_WAIT", "1") == "1"   # esperar a que Claude este libre
pending = []   # (destino, frase) dichas mientras Claude trabaja
mute_until = 0.0   # no oir el propio pitido de confirmacion
SOUNDS = BASE / "sounds"


def _make_sounds():
    import wave
    SOUNDS.mkdir(exist_ok=True)
    specs = {  # nombre: [(frecuencia Hz, segundos)]
        "switch": [(660, 0.07), (990, 0.09)],     # cambio de destino: sube
        "send": [(880, 0.09)],                    # enviar
        "pause": [(660, 0.07), (440, 0.1)],       # pausa: baja
        "error": [(220, 0.12), (180, 0.14)],      # nombre desconocido
    }
    for name, notes in specs.items():
        f = SOUNDS / f"{name}.wav"
        if f.exists():
            continue
        out = []
        for hz, dur in notes:
            t = np.arange(int(22050 * dur)) / 22050
            env = np.minimum(1, np.minimum(t / 0.008, (dur - t) / 0.02))
            out.append(0.35 * np.sin(2 * np.pi * hz * t) * env)
        pcm = (np.concatenate(out) * 32767).astype("<i2")
        with wave.open(str(f), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
            w.writeframes(pcm.tobytes())


def beep(name):
    global mute_until
    mute_until = time.monotonic() + 0.6
    try:
        subprocess.Popen(["paplay", str(SOUNDS / f"{name}.wav")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def claude_busy():
    try:  # el marcador caduca a los 10 min por si una interrupcion (Esc) no dispara Stop
        return time.time() - BUSY.stat().st_mtime < 600
    except OSError:
        return False

STATE = BASE / "listen.state"
HISTORY = BASE / "listen.history"
CONF = BASE / "listen.conf"


def conf_send():
    try:
        import json
        return bool(json.loads(CONF.read_text()).get("send", SEND))
    except Exception:
        return SEND


def add_history(text, sent):
    import json
    try:
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "text": text, "sent": sent},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
_last_state = None


def set_state(st):
    global _last_state
    if st != _last_state:
        _last_state = st
        STATE.write_text(st)


def notify(msg, ms=2500):
    subprocess.run(["notify-send", "-a", "Escucha", "-t", str(ms),
                    "-h", "string:x-canonical-private-synchronous:escucha", msg], check=False)


def claude_is_speaking():
    try:
        pid = int(voice.PIDFILE.read_text())
        os.killpg(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


LISTEN_DUCK = float(os.environ.get("LISTEN_DUCK", "0.25"))   # volumen de la musica mientras hablas
_duck_lock = threading.Lock()


def focus_ws(t):
    """Al cambiar de destino por voz, llevar la vista al workspace de esa terminal."""
    try:
        if t and t.get("workspace", {}).get("id", 0) > 0:
            subprocess.run(["hyprctl", "dispatch", "workspace", str(t["workspace"]["id"])],
                           stdout=subprocess.DEVNULL, check=False)
    except Exception as e:
        voice.log(f"listen: focus_ws error {e!r}")


def duck_async(down):
    """Baja/sube la musica con fade, sin bloquear la lectura del mic."""
    def run():
        with _duck_lock:
            try:
                if down:
                    voice.duck_volumes(LISTEN_DUCK, fade=0.25)
                else:
                    voice.restore_volumes(fade=0.6)
            except Exception as e:
                voice.log(f"listen: duck error {e!r}")
    threading.Thread(target=run, daemon=True).start()


class Vad:
    def __init__(self):
        from faster_whisper.vad import SileroVADModel
        import faster_whisper
        path = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
        self.m = SileroVADModel(str(path))
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), dtype="float32")
        self.c = np.zeros((1, 1, 128), dtype="float32")
        self.ctx = np.zeros((1, 64), dtype="float32")

    def prob(self, x):
        inp = np.concatenate([self.ctx, x.reshape(1, -1)], axis=1)
        out, self.h, self.c = self.m.session.run(None, {"input": inp, "h": self.h, "c": self.c})
        self.ctx = x.reshape(1, -1)[:, -64:]
        return float(np.asarray(out).ravel()[0])


def load_model():
    from faster_whisper import WhisperModel
    if DEVICE != "cpu":
        try:  # cuBLAS viene del paquete pip nvidia-cublas-cu12
            import ctypes, glob, site
            for d in site.getsitepackages():
                for f in glob.glob(d + "/nvidia/cublas/lib/libcublas*.so.12"):
                    ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
            return WhisperModel(MODEL, device="cuda", compute_type="int8_float16")
        except Exception as e:
            voice.log(f"listen: GPU no disponible ({e!r}), uso CPU")
    return WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=8)


def transcriber(q):
    model = load_model()
    import dictate
    while True:
        try:
            item = q.get(timeout=0.5)
        except queue.Empty:
            if pending and not paused and not (claude_busy() or claude_is_speaking()):
                flush(dictate)
            continue
        busy_inc(1)
        try:
            audio, short = item
            handle(model, audio, dictate, short)
        finally:
            busy_inc(-1)


def now_m():
    return time.monotonic()


def busy_inc(n):
    global busy
    busy += n


# Pista opcional para Whisper (vacía por defecto). Ej. rioplatense: LISTEN_PROMPT="Che, vos tenés que llamar; el fallo está en la calle, la llave y el pollo."
PROMPT = os.environ.get("LISTEN_PROMPT", "") or None
# Correcciones de palabra entera, solo casos seguros (Whisper escribe "sh" por "ll").
FIXES = {"fasho": "fallo", "fashos": "fallos"}
_FIX_RE = re.compile(r"\b(" + "|".join(FIXES) + r")\b", re.IGNORECASE)


def fix_rioplatense(text):
    def rep(m):
        w, r = m.group(0), FIXES[m.group(0).lower()]
        return r.upper() if w.isupper() else (r.capitalize() if w[0].isupper() else r)
    return _FIX_RE.sub(rep, text)


def handle(model, audio, dictate, short=False):
    t0 = time.monotonic()
    segs, _ = model.transcribe(audio, language=LANG, beam_size=5, vad_filter=True,
                               condition_on_previous_text=False, initial_prompt=PROMPT)
    text = fix_rioplatense(" ".join(s.text.strip() for s in segs).strip())
    dt = time.monotonic() - t0
    low = text.lower().strip()
    if len(low) < 2 or low in HALLUCINATIONS:
        voice.log(f"listen: descartado {text!r}")
        return
    if short:  # voz muy corta: solo se acepta si es un comando (enviar, pausa, modo manual...)
        import names as _n
        if _n.match_command(text) is None:
            voice.log(f"listen: descartado (muy corto) {text!r}")
            return
    voice.log(f"listen: {text!r} ({len(audio)/16000:.1f}s audio, {dt:.1f}s whisper)")
    print(f"🗣  {text}   [{dt:.1f}s]", flush=True)
    if DRY:
        add_history(text, False)
        return
    import names
    active = list(names.assign().values()) or [names.CENTRAL]
    if names.CENTRAL not in active:
        active.append(names.CENTRAL)
    # --- comandos de voz: solo si la frase ENTERA es el comando
    new, is_switch = names.match_switch(text, active)
    if is_switch:
        if new is None:
            voice.log(f"listen: destino desconocido en {text!r}")
            beep("error")
            notify("❓ No conozco esa terminal. Hay: " + ", ".join(sorted(active)), 3000)
        else:
            flush(dictate)  # lo ya dicho se queda con su destino
            names.set_current(new)
            beep("switch")
            t = dictate.claude_target(new)
            focus_ws(t := dictate.claude_target(new))
            notify(f"➡ Destino: {new}" + (f" (ws {t['workspace']['id']})" if t else " (ventana no encontrada)"), 2500)
            voice.log(f"listen: destino -> {new}")
        return
    # --- prefijo: 'alfa, <prompt>' o 'alfa' solo -> fija ese destino hasta que digas otro
    pre, rest = names.match_prefix(text, active)
    if pre:
        flush(dictate)  # lo ya dicho se queda con su destino
        if pre != names.current():
            names.set_current(pre)
            t = dictate.claude_target(pre)
            focus_ws(t)
            notify(f"➡ Destino: {pre}" + (f" (ws {t['workspace']['id']})" if t else " (ventana no encontrada)"), 2500)
            voice.log(f"listen: destino -> {pre} (por prefijo)")
        beep("switch")
        if not rest:
            return
        text = rest
    # --- modo interactivo por terminal: 'pasemos a modo interactivo' / 'modo normal' (frase entera)
    mode = names.match_mode(text)
    if mode:
        flush(dictate)
        tgt = names.current()
        names.set_mode(tgt, mode)
        beep("switch")
        notify(f"💬 {tgt}: modo " + ("interactivo" if mode == "interactive" else "normal"), 2500)
        voice.log(f"listen: modo {mode} en {tgt}")
        return
    cmd = names.match_command(text)
    if cmd == "pause":
        set_paused(True)
        beep("pause")
        return
    if cmd == "manual":
        flush(dictate)
        try:
            import json
            c = json.loads(CONF.read_text())
        except Exception:
            c = {}
        c["send"] = False
        CONF.write_text(json.dumps(c))
        beep("pause")
        notify("✋ Modo manual: el Enter lo mandás vos", 2500)
        voice.log("listen: modo manual (envio automatico apagado)")
        return
    if cmd == "send":
        flush(dictate)
        time.sleep(0.4)
        beep("send")
        dictate.send_return(dictate.claude_target())
        voice.log("listen: enviar por voz")
        return
    if dictate.claude_target() is None:
        add_history(text, False)  # nunca escribir fuera de la terminal de Claude
        voice.log("listen: sin terminal de Claude registrada, texto descartado")
        notify("Sin sesión de Claude abierta: no envié nada")
        return
    pending.append((names.current(), text))
    if WAIT and (claude_busy() or claude_is_speaking()):
        voice.log("listen: Claude ocupado, frase en espera")
        notify("⏳ En espera hasta que Claude termine", 1500)
        return
    flush(dictate)


def flush(dictate):
    if not pending:
        return
    groups = []   # frases consecutivas con el mismo destino se escriben juntas
    for tgt, t in pending:
        if groups and groups[-1][0] == tgt:
            groups[-1][1].append(t)
        else:
            groups.append((tgt, [t]))
    pending.clear()
    for tgt, parts in groups:
        text = " ".join(parts)
        try:
            voice.stop_current()
            send = conf_send()
            dictate.type_text(text if send else text + " ", enter=send, target_name=tgt)
            add_history(f"[{tgt}] {text}", send)
        except Exception as e:
            voice.log(f"listen: error al escribir: {e!r}")


def set_paused(p):
    global paused
    paused = p
    set_state("paused" if paused else "listening")
    print("⏸ pausado" if paused else "▶ escuchando", flush=True)
    notify("⏸ Escucha pausada" if paused else "🎙 Escuchando", 1500)


def on_usr1(*_):
    global paused
    paused = not paused
    set_state("paused" if paused else "listening")
    print("⏸ pausado" if paused else "▶ escuchando", flush=True)
    notify("⏸ Escucha pausada" if paused else "🎙 Escuchando", 1500)


def main():
    global paused
    if len(sys.argv) > 1 and sys.argv[1] == "toggle":
        try:
            os.kill(int(PID.read_text()), signal.SIGUSR1)
        except (FileNotFoundError, ValueError, ProcessLookupError):
            print("El demonio no está corriendo")
        return
    PID.write_text(str(os.getpid()))
    _make_sounds()
    set_state("loading")
    signal.signal(signal.SIGUSR1, on_usr1)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    q = queue.Queue()
    threading.Thread(target=transcriber, args=(q,), daemon=True).start()
    vad = Vad()
    p = subprocess.Popen(
        ["parecord", *voice.mic_args(), "--raw", "--format=s16le", "--rate=16000",
         "--channels=1", "--latency-msec=30"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if os.environ.get("LISTEN_START_PAUSED") == "1":
        paused = True
    set_state("paused" if paused else "listening")
    print(f"🎙 Escuchando (modelo {MODEL}, {'dry' if DRY else 'envía a Claude'}). Ctrl+C para salir.", flush=True)

    from collections import deque
    pre = deque(maxlen=int(PRE_ROLL * 16000 / CHUNK))
    frames, speaking, voiced, last_voice, hot = [], False, 0, 0.0, 0
    try:
        while True:
            data = p.stdout.read(CHUNK * 2)
            if not data or len(data) < CHUNK * 2:
                break
            x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            talking = claude_is_speaking()
            set_state("paused" if paused else "talking" if talking else
                      "hearing" if speaking else "transcribing" if busy else "listening")
            if paused or talking or now_m() < mute_until:
                if speaking or hot:
                    if speaking and not talking:
                        duck_async(False)
                    frames, speaking, voiced, hot = [], False, 0, 0
                    vad.reset()
                pre.clear()
                continue
            pr = vad.prob(x)
            now = time.monotonic()
            if not speaking:
                pre.append(x)
                hot = hot + 1 if pr > THR else 0
                if hot >= 3:  # ~100 ms de voz seguida: empieza una frase
                    speaking, frames, voiced, last_voice = True, list(pre), 0, now
                    if not DRY:
                        duck_async(True)
            else:
                frames.append(x)
                if pr > THR - 0.15:
                    last_voice = now
                if pr > THR:
                    voiced += 1
                done = now - last_voice > SILENCE or len(frames) * CHUNK / 16000 > MAX_UTTERANCE
                if done:
                    v = voiced * CHUNK / 16000
                    if v >= SHORT_SPEECH:
                        q.put((np.concatenate(frames), v < MIN_SPEECH))
                    frames, speaking, voiced, hot = [], False, 0, 0
                    pre.clear()
                    vad.reset()
                    duck_async(False)
    except KeyboardInterrupt:
        pass
    finally:
        voice.restore_volumes()
        p.terminate()
        PID.unlink(missing_ok=True)
        STATE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
