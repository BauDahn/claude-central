"""Lógica pura de voz para Station: extracción de <voz>, comandos, audio PulseAudio y detección de entorno."""
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from agent_station.home import home

VOCES_KOKORO = (
    "af_heart",
    "af_bella",
    "af_nova",
    "af_sky",
    "am_adam",
    "am_michael",
    "bf_emma",
    "bm_george",
)

VOZ_TOP = re.compile(r"\A\s*<voz>(.*?)</voz>", re.S)
VOZ_ANY = re.compile(r"<voz>(.*?)</voz>", re.S)
VOZ_STRIP = re.compile(r"<voz>.*?(</voz>\s*|$)", re.S)
SPANISH_CHARS = re.compile(r"[áéíóúñüÁÉÍÓÚÑÜ¿¡]")

HALLUCINATIONS = {
    "gracias", "gracias.", "gracias por ver el video", "gracias por ver el video.",
    "subtítulos realizados por la comunidad de amara.org", "suscríbete", "...",
    "thank you", "thank you.", "you", "bye", "bye.",
}

RIOPLATENSE_PROMPT = (
    "Che, vos tenés que llamar; yo me llamo Bauti. El fallo está en la calle, la llave y el pollo."
)
_FIXES = {"fasho": "fallo", "fashos": "fallos"}
_FIX_RE = re.compile(r"\b(" + "|".join(_FIXES) + r")\b", re.IGNORECASE)

_HEADSET_PATTERNS = ("bluez_output.", "Razer_Barracuda", "headset", "headphone")

SEND_WORDS = {
    "enviar", "envia", "enviar lo", "envialo", "enviarlo", "enviar mensaje", "envia mensaje",
    "envia el mensaje", "enviar el mensaje", "manda", "mandalo", "mandar", "manda el mensaje",
    "enter", "intro", "enviado", "envia ya", "manda eso", "manda esto", "envia eso", "envia esto",
    "mandar eso", "enviar eso", "mandar mensaje", "manda mensaje", "mandalo ya", "envialo ya", "dale enter",
}
PAUSE_WORDS = {
    "pausa", "pausar", "pausa el microfono", "pausa microfono", "pausar microfono",
    "pausa la escucha", "pausar escucha", "pausa por favor", "pausar por favor",
}
MANUAL_WORDS = {
    "modo manual", "pasa a modo manual", "pasar a modo manual", "pasemos a modo manual",
    "envio manual", "desactiva el envio automatico", "apaga el envio automatico",
    "quita el envio automatico", "modo no automatico", "sin envio automatico",
}
STOP_TTS_WORDS = {
    "callate", "silencio", "para de hablar", "deja de hablar", "basta", "corta el audio",
}
MODE_RE = re.compile(
    r"^(?:(?:por favor|oye|ahora)\s+)?"
    r"(?:(?P<off>sal(?:ir)?|salgamos|desactiva(?:r)?|quita(?:r)?|apaga(?:r)?)\s+(?:del?\s+|el\s+)?(?:modo\s+)?(?:interactivo|conversacional)"
    r"|(?:(?:pasemos|pasa|pasar|activa|activar|pon|poner|ponte|cambia|cambiemos|entra|entremos|vamos)\s+(?:a|al|en|el)?\s*)?(?:el\s+)?modo\s+(?P<m>interactivo|conversacional|normal))$"
)
PREFIX_RE = re.compile(r"^\W*([^\W\d_]+)\W*(.*)$", re.S)


def voz_home() -> Path:
    d = home() / "voz"
    d.mkdir(parents=True, exist_ok=True)
    return d


def modelos_kokoro() -> tuple[Path | None, Path | None]:
    """Busca los modelos locales de Kokoro ONNX sin descargar nada."""
    candidates = []
    if env := os.environ.get("STATION_VOICE_MODELS"):
        candidates.append(Path(env))
    candidates.extend([
        home() / "voz" / "models",
        Path.home() / ".local" / "share" / "claude-voice" / "models",
    ])
    for d in candidates:
        onnx = d / "kokoro-v1.0.onnx"
        voices = d / "voices-v1.0.bin"
        if onnx.exists() and voices.exists():
            return onnx, voices
    return None, None


def _python_tiene_voz(exe: str) -> bool:
    try:
        r = subprocess.run(
            [exe, "-c", "import kokoro_onnx, faster_whisper, soundfile, numpy"],
            capture_output=True, text=True, timeout=6,
        )
        return r.returncode == 0
    except Exception:
        return False


def python_voz() -> str | None:
    """Devuelve el ejecutable Python con kokoro_onnx + faster_whisper disponibles, o None."""
    cands = []
    if env := os.environ.get("STATION_VOICE_PYTHON"):
        cands.append(env)
    cands.append(sys.executable)
    legacy_venv = Path.home() / ".local" / "share" / "claude-voice" / "venv" / "bin" / "python"
    if legacy_venv.exists():
        cands.append(str(legacy_venv))
    seen = set()
    for c in cands:
        if not c or c in seen:
            continue
        seen.add(c)
        if Path(c).exists() and _python_tiene_voz(c):
            return c
    return None


def diagnostico_voz() -> dict:
    onnx, voices = modelos_kokoro()
    py = python_voz()
    return {
        "python": py,
        "kokoro_onnx": str(onnx) if onnx else None,
        "kokoro_voices": str(voices) if voices else None,
        "parecord": shutil.which("parecord"),
        "paplay": shutil.which("paplay"),
        "pactl": shutil.which("pactl"),
        "listo": bool(py and onnx and voices and shutil.which("parecord") and shutil.which("paplay")),
    }


def extraer_voz(text: str) -> str | None:
    """Extrae la etiqueta <voz> al inicio o la última completa (None si no hay cerrada)."""
    if not text:
        return None
    m = VOZ_TOP.match(text)
    if m:
        return m.group(1).strip()
    end = text.rfind("</voz>")
    start = text.rfind("<voz>", 0, end) if end != -1 else -1
    return text[start + 5:end].strip() if start != -1 else None


def quitar_voz(text: str) -> str:
    """Quita etiquetas <voz>...</voz> (incluso una parcial al final mientras streamea)."""
    return VOZ_STRIP.sub("", text or "").strip()


def limpiar_para_tts(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[*_#>|~]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def dividir_frases(text: str) -> list[str]:
    out = []
    for sent in re.split(r"(?<=[.!?:;])\s+", text):
        if len(sent) > 70:
            out.extend(re.split(r"(?<=,)\s+", sent))
        else:
            out.append(sent)
    return [p.strip() for p in out if p.strip()]


def tiene_espanol(text: str) -> bool:
    return bool(SPANISH_CHARS.search(text or ""))


def fix_rioplatense(text: str) -> str:
    def rep(m):
        w, r = m.group(0), _FIXES[m.group(0).lower()]
        return r.upper() if w.isupper() else (r.capitalize() if w[0].isupper() else r)
    return _FIX_RE.sub(rep, text)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9ñ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fold(w: str) -> str:
    w = norm(w).replace(" ", "")
    w = w.replace("ph", "f").replace("th", "t").replace("qu", "k").replace("ch", "x")
    w = re.sub(r"c(?=[ei])", "s", w)
    w = w.replace("c", "k").replace("z", "s").replace("v", "b").replace("y", "i")
    w = w.replace("w", "u").replace("h", "")
    return re.sub(r"(.)\1+", r"\1", w)


def match_command(text: str) -> str | None:
    t = norm(text)
    t = re.sub(r"^(por favor|oye|ahora)\s+", "", t)
    t = re.sub(r"\s+por favor$", "", t)
    if t in SEND_WORDS:
        return "send"
    if t in PAUSE_WORDS:
        return "pause"
    if t in MANUAL_WORDS:
        return "manual"
    if t in STOP_TTS_WORDS:
        return "stop_tts"
    return None


def match_mode(text: str) -> str | None:
    m = MODE_RE.match(re.sub(r"\s+por favor$", "", norm(text)))
    if not m:
        return None
    if m.group("off") or m.group("m") == "normal":
        return "normal"
    return "interactive"


def match_agent_prefix(text: str, active_names: list[str], min_ratio: float = 0.85) -> tuple[str | None, str]:
    """Si la frase empieza con el nombre de un agente/rol ('constructor, hacé X'), devuelve (agente, resto)."""
    m = PREFIX_RE.match(text or "")
    if not m or not active_names:
        return None, text
    cand = fold(m.group(1))
    if not cand:
        return None, text
    best, score, second = None, 0.0, 0.0
    for n in active_names:
        r = difflib.SequenceMatcher(None, cand, fold(n)).ratio()
        if r > score:
            best, score, second = n, r, score
        elif r > second:
            second = r
    if best and score >= min_ratio and score - second >= 0.05:
        return best, m.group(2).strip()
    return None, text


def instrucciones_voz() -> str:
    return (
        "## Voz (TTS local)\n"
        "El usuario escucha tus respuestas con un TTS local que lee SOLO lo que está dentro de `<voz>...</voz>`.\n"
        "- Al PRINCIPIO de cada respuesta (primera línea), escribí `<voz>...</voz>` con 1 o 2 frases cortas, "
        "**siempre en inglés**, naturales y conversacionales.\n"
        "- Nunca pongas código, rutas, comandos, URLs, listas ni markdown dentro de `<voz>`.\n"
        "- Resumí lo importante: qué hiciste, qué resultado hubo o qué necesitás que decida. El resto de la respuesta sigue en español."
    )


def instrucciones_interactivo() -> str:
    return (
        "[MODO INTERACTIVO activo: conversación de ida y vuelta por voz]\n"
        "- La línea `<voz>` es 1 o 2 frases cortas y conversacionales en inglés; si necesitás algo del usuario, terminala con UNA pregunta concreta.\n"
        "- Si falta información, preguntá en vez de suponer. Una pregunta a la vez.\n"
        "- Si el resultado es largo, resumilo hablado y preguntá si quiere el detalle; no leas listas ni datos largos.\n"
        "- Al terminar una tarea, decí en voz qué quedó hecho y preguntá cómo seguir.\n"
        "- Mantené también breve el texto escrito."
    )


# ---------------------------------------------------------------- audio / PulseAudio
def auriculares() -> str | None:
    try:
        out = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=2).stdout
        names = [l.split("\t")[1] for l in out.splitlines() if "\t" in l]
    except Exception:
        return None
    for pat in _HEADSET_PATTERNS:
        for n in names:
            if pat.lower() in n.lower():
                return n
    return None


def paplay_cmd(path) -> list[str]:
    s = auriculares()
    return ["paplay", *(["--device=" + s] if s else []), str(path)]


def mic_args() -> list[str]:
    name = os.environ.get("STATION_VOICE_SOURCE") or os.environ.get("CLAUDE_VOICE_SOURCE", "")
    if not name:
        try:
            out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=2).stdout
            name = next((l.split("\t")[1] for l in out.splitlines() if "\tbluez_input." in l), "")
        except Exception:
            pass
    for f in (voz_home() / "source", Path.home() / ".local" / "share" / "claude-voice" / "source"):
        if not name and f.exists():
            name = f.read_text().strip()
            if name:
                break
    return ["--device=" + name] if name else []


def bt_headset() -> bool:
    try:
        out = subprocess.run(["pactl", "list", "short", "cards"], capture_output=True, text=True, timeout=2).stdout
        return "bluez_card." in out
    except Exception:
        return False


def _ramp(frm, to, fade, steps=6):
    for n in range(1, steps + 1):
        for idx, a in frm.items():
            b = to[idx]
            vals = [int(x + (y - x) * n / steps) for x, y in zip(a, b)]
            subprocess.run(["pactl", "set-sink-input-volume", idx, *map(str, vals)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if n < steps:
            time.sleep(fade / steps)


def _duck_file() -> Path:
    return voz_home() / "ducked.json"


def _locked(fn):
    def wrapper(*a, **k):
        with open(voz_home() / "duck.lock", "a+") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            return fn(*a, **k)
    return wrapper


@_locked
def restore_volumes(fade: float = 0.0):
    df = _duck_file()
    try:
        saved = json.loads(df.read_text())
    except (FileNotFoundError, ValueError):
        return
    df.unlink(missing_ok=True)
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
        subprocess.run(["pactl", "set-sink-input-volume", idx, *map(str, vals)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


@_locked
def duck_volumes(factor: float = 0.3, fade: float = 0.0):
    df = _duck_file()
    if df.exists():
        return
    try:
        out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"],
                             capture_output=True, text=True, timeout=3).stdout
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
    df.write_text(json.dumps(saved))
    if fade > 0:
        _ramp(saved, {k: [int(v * factor) for v in vs] for k, vs in saved.items()}, fade)
        return
    for idx, vals in saved.items():
        low = [int(v * factor) for v in vals]
        subprocess.run(["pactl", "set-sink-input-volume", idx, *map(str, low)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def already_spoken(session: str, voz_text: str) -> bool:
    sp = voz_home() / "spoken.json"
    h = hashlib.md5(voz_text.strip().encode()).hexdigest()
    try:
        d = json.loads(sp.read_text())
    except (OSError, ValueError):
        d = {}
    if d.get(session) == h:
        return True
    d[session] = h
    sp.write_text(json.dumps(d))
    return False


def stop_detached_pid():
    pf = voz_home() / "playing.pid"
    try:
        pid = int(pf.read_text())
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
    pf.unlink(missing_ok=True)
    restore_volumes()
