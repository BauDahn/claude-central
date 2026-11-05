"""Nombres de terminales Claude (central + letras griegas) y destino del dictado.

- central: la terminal principal (central.pid).
- Las demas kitty registradas reciben el primer nombre griego libre; se guarda
  en names.json {pid: nombre} y se mantiene mientras viva esa ventana.
- target.txt guarda el nombre al que va el dictado (def: central si existe).
"""
import difflib
import fcntl
import json
import os
import re
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
NAMES = BASE / "names.json"
TARGET = BASE / "target.txt"
LOCK = BASE / "names.lock"
SESSIONS = BASE / "sessions"
GREEK = ["alfa", "beta", "gamma", "delta", "epsilon", "zeta", "sigma", "omega",
         "kappa", "lambda", "theta", "iota"]
CENTRAL = "central"


def _alive(pid):
    return Path(f"/proc/{pid}").exists()


def central_pid():
    try:
        return int((BASE / "central.pid").read_text())
    except (OSError, ValueError):
        return None


def _cmdline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
    except OSError:
        return ""


def registered_pids():
    # Solo kitty vivos: un pid muerto reutilizado por otro proceso (ej. Spotify) no es una sesion
    return sorted(int(p.name) for p in SESSIONS.glob("*")
                  if p.name.isdigit() and _alive(int(p.name)) and "kitty" in _cmdline(int(p.name)))


ALIAS = {"alpha": "alfa"}


def preferred_name(pid):
    """Nombre fijo si la kitty se lanzo como --class agente-<nombre> (alpha->alfa, beta, gamma...)."""
    m = re.search(r"--class agente-([a-z0-9]+)", _cmdline(pid))
    return ALIAS.get(m.group(1), m.group(1)) if m else None


def assign():
    """Devuelve {pid: nombre} para las sesiones vivas, asignando los que falten."""
    with open(LOCK, "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            cur = {int(k): v for k, v in json.loads(NAMES.read_text()).items()}
        except (OSError, ValueError):
            cur = {}
        cen = central_pid()
        live = [p for p in registered_pids()]
        out = {p: preferred_name(p) or n for p, n in cur.items() if p in live and p != cen}
        for p in live:
            if p != cen and p not in out and preferred_name(p):
                out[p] = preferred_name(p)
        used = set(out.values())
        for p in live:
            if p == cen or p in out:
                continue
            free = [n for n in GREEK if n not in used]
            n = free[0] if free else f"extra{len(used) + 1}"
            out[p] = n
            used.add(n)
        if out != cur:
            NAMES.write_text(json.dumps({str(k): v for k, v in out.items()}))
        if cen and cen in live:
            out = {**out, cen: CENTRAL}
        return out


def pid_for(name):
    for p, n in assign().items():
        if n == name:
            return p
    return None


def current():
    try:
        return TARGET.read_text().strip() or CENTRAL
    except OSError:
        return CENTRAL


def set_current(name):
    TARGET.write_text(name)


# ------------------------------------------------------------ reconocimiento
def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9ñ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fold(w):
    """Aproximacion fonetica espanola para tolerar errores de Whisper."""
    w = norm(w).replace(" ", "")
    w = w.replace("ph", "f").replace("th", "t").replace("qu", "k").replace("ch", "x")
    w = re.sub(r"c(?=[ei])", "s", w)
    w = w.replace("c", "k").replace("z", "s").replace("v", "b").replace("y", "i")
    w = w.replace("w", "u").replace("h", "")
    return re.sub(r"(.)\1+", r"\1", w)


SWITCH = re.compile(
    r"^(?:(?:por favor|oye|ahora)\s+)?"
    r"(?:pasa|pasar|paso|pasas|pasame|pasa te|ve|vete|ir|voy|vuelve|vuelva|volver|vuelvo|cambia|cambiar|cambiate|"
    r"salta|saltar|dictado|dicta|dictar|manda|mandar|ponme|pon|habla|hablar|escribe|escribir|muevete|mover)"
    r"(?:\s+(?:el\s+)?(?:dictado|texto|todo))?"
    r"\s*(?:a la|al|a|en la|en el|en|hacia|con|para|para la|para el)?\s*"
    r"(?:(?:la|el)\s+)?(?:(?:terminal|sesion|consola|ventana)\s+)?"
    r"(?:(?:de|del)\s+)?(?P<name>[a-zñ ]{2,20})$")


def match_switch(text, active_names, min_ratio=0.74):
    """Si text es 'pasa a <nombre>' (frase entera), devuelve (nombre|None, es_cambio).

    es_cambio True con nombre None = parecia un cambio pero el nombre no existe."""
    t = re.sub(r"\s+por favor$", "", norm(text))
    m = SWITCH.match(t)
    if not m:
        return None, False
    cand = fold(m.group("name"))
    if not cand:
        return None, False
    best, score, second = None, 0.0, 0.0
    for n in active_names:
        r = difflib.SequenceMatcher(None, cand, fold(n)).ratio()
        if r > score:
            best, score, second = n, r, score
        elif r > second:
            second = r
    if best and score >= min_ratio and score - second >= 0.05:
        return best, True
    # Parece un cambio solo si el 'nombre' se parece a algun nombre griego
    # o a central (para no tragarse frases como "ve a comprar pan").
    known = list(GREEK) + [CENTRAL]
    looks = any(difflib.SequenceMatcher(None, cand, fold(n)).ratio() >= 0.8 for n in known)
    return None, looks


SEND_WORDS = {"enviar", "envia", "enviar lo", "envialo", "enviarlo", "enviar mensaje", "envia mensaje",
              "envia el mensaje", "enviar el mensaje", "manda", "mandalo", "mandar", "manda el mensaje",
              "enter", "intro", "enviado", "envia ya", "manda eso", "manda esto", "envia eso", "envia esto",
              "mandar eso", "enviar eso", "mandar mensaje", "manda mensaje", "mandalo ya", "envialo ya", "dale enter"}
PAUSE_WORDS = {"pausa", "pausar", "pausa el microfono", "pausa microfono", "pausar microfono",
               "pausa la escucha", "pausar escucha", "pausa por favor", "pausar por favor"}


MANUAL_WORDS = {"modo manual", "pasa a modo manual", "pasar a modo manual", "pasemos a modo manual",
                "envio manual", "desactiva el envio automatico", "apaga el envio automatico",
                "quita el envio automatico", "modo no automatico", "sin envio automatico"}


def match_command(text):
    t = norm(text)
    t = re.sub(r"^(por favor|oye|ahora)\s+", "", t)
    t = re.sub(r"\s+por favor$", "", t)
    if t in SEND_WORDS:
        return "send"
    if t in PAUSE_WORDS:
        return "pause"
    if t in MANUAL_WORDS:
        return "manual"
    return None


PREFIX = re.compile(r"^\W*([^\W\d_]+)\W*(.*)$", re.S)


def match_prefix(text, active_names, min_ratio=0.85):
    """Si la frase EMPIEZA con un nombre de terminal ('alfa, explicame X'),
    devuelve (nombre, resto). Si no, (None, text). Solo nombres activos."""
    m = PREFIX.match(text)
    if not m:
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


# ------------------------------------------------------------ modo interactivo
MODES = BASE / "modes.json"
MODE_RE = re.compile(
    r"^(?:(?:por favor|oye|ahora)\s+)?"
    r"(?:(?P<off>sal(?:ir)?|salgamos|desactiva(?:r)?|quita(?:r)?|apaga(?:r)?)\s+(?:del?\s+|el\s+)?(?:modo\s+)?(?:interactivo|conversacional)"
    r"|(?:(?:pasemos|pasa|pasar|activa|activar|pon|poner|ponte|cambia|cambiemos|entra|entremos|vamos)\s+(?:a|al|en|el)?\s*)?(?:el\s+)?modo\s+(?P<m>interactivo|conversacional|normal))$")


def match_mode(text):
    """'pasemos a modo interactivo' -> 'interactive'; 'modo normal' -> 'normal'; otro -> None."""
    m = MODE_RE.match(re.sub(r"\s+por favor$", "", norm(text)))
    if not m:
        return None
    if m.group("off") or m.group("m") == "normal":
        return "normal"
    return "interactive"


def _modes():
    try:
        return json.loads(MODES.read_text())
    except (OSError, ValueError):
        return {}


def get_mode(name):
    return _modes().get(name, "normal")


def set_mode(name, mode):
    with open(LOCK, "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = _modes()
        if mode == "normal":
            d.pop(name, None)
        else:
            d[name] = mode
        MODES.write_text(json.dumps(d))
