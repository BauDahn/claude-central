#!/usr/bin/env python3
"""Voz para Claude Code (Kokoro, local).

Uso:
  voice.py speak   -> hook Stop: lee el ultimo <voz>...</voz> de la respuesta
  voice.py stop    -> hook UserPromptSubmit: corta el audio en curso
  voice.py say "t" -> prueba manual

Extras:
  - Barge-in: mientras habla, vigila el microfono y se calla si hablas vos.
  - Ducking: baja el volumen de lo que suene (Spotify, etc.) mientras habla.
  - Solo ingles: si el texto trae caracteres del espanol, no lo lee.

Variables: CLAUDE_VOICE, CLAUDE_VOICE_SPEED, CLAUDE_VOICE_LANG,
           CLAUDE_VOICE_DUCK (0-1, factor de volumen, def 0.3),
           CLAUDE_VOICE_BARGE (1/0, def 1).
"""
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PIDFILE = BASE / "playing.pid"
DUCKFILE = BASE / "ducked.json"
LOGFILE = BASE / "error.log"
VOICE = os.environ.get("CLAUDE_VOICE", "af_heart")
SPEED = float(os.environ.get("CLAUDE_VOICE_SPEED", "1.05"))
LANG = os.environ.get("CLAUDE_VOICE_LANG", "en-us")
DUCK = float(os.environ.get("CLAUDE_VOICE_DUCK", "0.3"))
BARGE = os.environ.get("CLAUDE_VOICE_BARGE", "1") == "1"

DEVNULL = subprocess.DEVNULL


DEBUGLOG = BASE / "debug.log"


def log(msg):
    """Registro de depuracion (se vacia solo al pasar de 200 KB)."""
    try:
        if DEBUGLOG.exists() and DEBUGLOG.stat().st_size > 200_000:
            DEBUGLOG.write_text("")
        with open(DEBUGLOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + f"[{os.getpid()}] " + msg + "\n")
    except OSError:
        pass


def mic_args():
    """Microfono a usar: $CLAUDE_VOICE_SOURCE, o el nombre guardado en el archivo
    `source` (junto a este script); si no hay ninguno, el microfono por defecto."""
    name = os.environ.get("CLAUDE_VOICE_SOURCE", "")
    f = BASE / "source"
    if not name and f.exists():
        name = f.read_text().strip()
    return ["--device=" + name] if name else []
SPANISH_CHARS = re.compile(r"[áéíóúñüÁÉÍÓÚÑÜ¿¡]")


# ---------------------------------------------------------------- sesiones
SESSIONS = BASE / "sessions"


def register_session():
    """Los hooks de Claude corren con el entorno de su terminal: guardamos el
    pid de kitty para que el dictado sepa en que ventana escribir."""
    pid = os.environ.get("KITTY_PID", "")
    if pid.isdigit():
        SESSIONS.mkdir(exist_ok=True)
        (SESSIONS / pid).touch()
        if os.environ.get("CLAUDE_CENTRAL") == "1":  # el Claude principal
            (BASE / "central.pid").write_text(pid)
        try:  # nombre estable (central / alfa / beta...) para el cambio de destino por voz
            import names
            names.assign()
        except Exception as e:
            log(f"names: {e!r}")


# ---------------------------------------------------------------- volumen
def _ramp(frm, to, fade, steps=6):
    """Cambia el volumen de frm a to (dict idx->lista) en `fade` s, de forma lineal."""
    for n in range(1, steps + 1):
        for idx, a in frm.items():
            b = to[idx]
            vals = [int(x + (y - x) * n / steps) for x, y in zip(a, b)]
            subprocess.run(["pactl", "set-sink-input-volume", idx, *map(str, vals)],
                           stdout=DEVNULL, stderr=DEVNULL, check=False)
        if n < steps:
            time.sleep(fade / steps)


def _restore_volumes(fade=0.0):
    try:
        saved = json.loads(DUCKFILE.read_text())
    except (FileNotFoundError, ValueError):
        return
    DUCKFILE.unlink(missing_ok=True)
    if fade > 0:
        try:
            out = json.loads(subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"],
                                            capture_output=True, text=True, timeout=3).stdout)
            cur = {str(i["index"]): [c["value"] for c in i.get("volume", {}).values()] for i in out}
            frm = {k: cur[k] for k in saved if cur.get(k) and len(cur[k]) == len(saved[k])}
            _ramp(frm, saved, fade)
        except Exception:
            pass
    for idx, vals in saved.items():
        subprocess.run(
            ["pactl", "set-sink-input-volume", idx, *map(str, vals)],
            stdout=DEVNULL, stderr=DEVNULL, check=False,
        )


def _duck_volumes(factor=None, fade=0.0):
    if factor is None:
        factor = DUCK
    if DUCKFILE.exists():  # ya estaba bajado: conservar los originales
        return
    try:
        out = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True, text=True, timeout=3,
        ).stdout
        inputs = json.loads(out)
    except Exception:
        return
    saved = {}
    for i in inputs:
        if i.get("properties", {}).get("application.name") == "paplay":
            continue
        vals = [c["value"] for c in i.get("volume", {}).values()]
        if vals:
            saved[str(i["index"])] = vals
    if not saved:
        return
    DUCKFILE.write_text(json.dumps(saved))
    if fade > 0:
        _ramp(saved, {k: [int(v * factor) for v in vs] for k, vs in saved.items()}, fade)
        return
    for idx, vals in saved.items():
        low = [int(v * factor) for v in vals]
        subprocess.run(
            ["pactl", "set-sink-input-volume", idx, *map(str, low)],
            stdout=DEVNULL, stderr=DEVNULL, check=False,
        )


# Lock entre procesos: evita que un duck capture volumenes a medio restaurar
# (eso "guardaba" el volumen bajo como original y la musica se quedaba baja).
import fcntl as _fcntl


def _locked(fn):
    def wrapper(*a, **k):
        with open(BASE / "duck.lock", "a+") as lk:
            _fcntl.flock(lk, _fcntl.LOCK_EX)
            return fn(*a, **k)
    return wrapper


restore_volumes = _locked(_restore_volumes)
duck_volumes = _locked(_duck_volumes)


# ---------------------------------------------------------------- control
def stop_current():
    """Corta el audio en curso (y espera a que restaure los volumenes)."""
    try:
        pid = int(PIDFILE.read_text())
    except (FileNotFoundError, ValueError):
        pid = None
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        else:
            for _ in range(40):
                try:
                    os.killpg(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
    PIDFILE.unlink(missing_ok=True)
    restore_volumes()  # por si el proceso anterior murio sin restaurar


# ---------------------------------------------------------------- texto
def last_assistant_text(data):
    msg = data.get("last_assistant_message")
    if isinstance(msg, str) and msg:
        return msg
    path = data.get("transcript_path")
    if not path:
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                m = e.get("message") or {}
                if e.get("type") == "assistant" or m.get("role") == "assistant":
                    c = m.get("content")
                    if isinstance(c, str):
                        last = c
                    elif isinstance(c, list):
                        t = "".join(b.get("text", "") for b in c if b.get("type") == "text")
                        if t:
                            last = t
    except OSError:
        pass
    return last


def clean(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[*_#>|~]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text):
    out = []
    for sent in re.split(r"(?<=[.!?:;])\s+", text):
        # frases largas: partir en comas para que la primera pieza suene antes
        if len(sent) > 70:
            out.extend(re.split(r"(?<=,)\s+", sent))
        else:
            out.append(sent)
    return [p.strip() for p in out if p.strip()]


# ---------------------------------------------------------------- barge-in
def barge_in_watch():
    """Si detecta tu voz en el microfono, se corta a si mismo."""
    import numpy as np

    p = subprocess.Popen(
        ["parecord", *mic_args(), "--raw", "--format=s16le", "--rate=16000",
         "--channels=1", "--latency-msec=30"],
        stdout=subprocess.PIPE, stderr=DEVNULL,
    )
    chunk = 960  # 30 ms
    noise, thr, hot = [], None, 0
    while True:
        data = p.stdout.read(chunk)
        if not data or len(data) < chunk:
            return
        x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(x * x)))
        if thr is None:
            noise.append(rms)
            if len(noise) >= 15:
                floor = float(np.percentile(noise, 20))
                thr = min(max(floor * 4, 300.0), 1200.0)
            continue
        hot = hot + 1 if rms > thr else 0
        if hot >= 8:  # ~240 ms seguidos de voz
            log(f"barge-in: corte por voz en el micro (rms={rms:.0f}, umbral={thr:.0f})")
            os.kill(os.getpid(), signal.SIGTERM)
            return


# ---------------------------------------------------------------- audio
def play(text, tmpdir):
    from kokoro_onnx import Kokoro
    import soundfile as sf

    kokoro = Kokoro(str(BASE / "models/kokoro-v1.0.onnx"), str(BASE / "models/voices-v1.0.bin"))
    if BARGE:
        threading.Thread(target=barge_in_watch, daemon=True).start()

    q = queue.Queue(maxsize=2)

    def producer():
        for n, s in enumerate(split_sentences(text)):
            samples, sr = kokoro.create(s, voice=VOICE, speed=SPEED, lang=LANG)
            p = os.path.join(tmpdir, f"{n}.wav")
            sf.write(p, samples, sr)
            q.put(p)
        q.put(None)

    threading.Thread(target=producer, daemon=True).start()
    first = True
    while True:
        p = q.get()
        if p is None:
            break
        if first:
            duck_volumes()
            first = False
        subprocess.run(["paplay", p], check=False)
        os.unlink(p)


def run_detached(text):
    stop_current()
    if os.fork() != 0:
        return
    os.setsid()
    PIDFILE.write_text(str(os.getpid()))
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    tmpdir = tempfile.mkdtemp(prefix="cvoice-")

    def cleanup_and_exit(*_):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            os.killpg(os.getpgrp(), signal.SIGTERM)  # paplay / parecord
        except Exception:
            pass
        restore_volumes()
        shutil.rmtree(tmpdir, ignore_errors=True)
        PIDFILE.unlink(missing_ok=True)
        os._exit(0)

    signal.signal(signal.SIGTERM, cleanup_and_exit)
    try:
        play(text, tmpdir)
    except BaseException:
        import traceback
        LOGFILE.write_text(traceback.format_exc())
    cleanup_and_exit()


def speak_text(text):
    text = clean(text)
    if not text:
        return
    if SPANISH_CHARS.search(text):
        log(f"omitido por caracteres del espanol: {text[:80]!r}")
        LOGFILE.write_text("Texto con caracteres del espanol, no se lee: " + text + "\n")
        return
    run_detached(text)


SPOKEN = BASE / "spoken.json"
VOZ_TOP = re.compile(r"\A\s*<voz>(.*?)</voz>", re.S)


def pick_voz(text):
    """La etiqueta <voz> al principio del mensaje; si no, la ultima (compatibilidad)."""
    m = VOZ_TOP.match(text)
    if m:
        return m.group(1)
    end = text.rfind("</voz>")
    start = text.rfind("<voz>", 0, end) if end != -1 else -1
    return text[start + 5:end] if start != -1 else None


def already_spoken(session, voz):
    """True si ya se leyo esa misma etiqueta en esta sesion; si no, la anota."""
    import hashlib
    h = hashlib.md5(voz.strip().encode()).hexdigest()
    try:
        d = json.loads(SPOKEN.read_text())
    except (OSError, ValueError):
        d = {}
    if d.get(session) == h:
        return True
    d[session] = h
    SPOKEN.write_text(json.dumps(d))
    return False


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "speak"
    register_session()  # apunta que esta terminal (kitty) tiene una sesion de Claude
    if mode == "register":
        return
    if mode == "stop":
        (BASE / "busy").touch()  # Claude empieza a trabajar
        log("stop (UserPromptSubmit): se corta el audio")
        stop_current()
        try:  # modo interactivo por terminal: se inyecta como contexto del prompt
            import names
            n = names.assign().get(int(os.environ.get("KITTY_PID", "0")))
            if n and names.get_mode(n) == "interactive":
                print((BASE / "interactive.md").read_text())
        except Exception as e:
            log(f"modo interactivo: {e!r}")
        return
    if mode == "say":
        speak_text(" ".join(sys.argv[2:]))
        return
    if os.environ.get("CLAUDE_CENTRAL") != "1":  # solo central habla; el resto queda mudo
        if mode != "early":
            (BASE / "busy").unlink(missing_ok=True)  # conservar la señal de "libre"
        return
    early = mode == "early"   # PreToolUse/PostToolUse: leer el resumen en cuanto existe
    if not early:
        (BASE / "busy").unlink(missing_ok=True)  # Claude termino: esta libre
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    if data.get("stop_hook_active") and not early:
        return
    text = last_assistant_text({"transcript_path": data.get("transcript_path")} if early else data)
    voz = pick_voz(text)
    if early:
        log(f"early: voz={'si' if voz else 'no'} tool={data.get('tool_name')}")
        if voz and not already_spoken(data.get("session_id", "?"), voz):
            speak_text(voz)
        return
    log(f"Stop: claves={sorted(data)} last_assistant_message={'last_assistant_message' in data} "
        f"len={len(text)} etiqueta={'si' if voz else 'NO'} inicio={text[:50]!r} fin={text[-60:]!r}")
    if voz and not already_spoken(data.get("session_id", "?"), voz):
        speak_text(voz)


if __name__ == "__main__":
    main()
