"""Asignación estable de nombres griegos/mitológicos por sesión y alias para IDs históricos."""
import fcntl
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

from . import eventos
from .home import home

GRIEGAS = (
    "alfa", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi",
    "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
)
MITOS = (
    "orion", "atlas", "hermes", "apolo", "atenea", "artemisa", "zeus", "hera",
    "poseidon", "ares", "hefesto", "dioniso", "helios", "selene", "iris", "eos",
    "andromeda", "pegaso", "cassiopea", "fenix", "draco", "lyra", "cygnus", "vega",
    "sirio", "polaris", "altair", "antares", "rigel", "procyon",
)
NOMBRES = GRIEGAS + MITOS
_NOMBRES_SET = set(NOMBRES)
LEGACY_ID_RE = re.compile(r"^(?:agy|codex|claude)-\d{6}$")


def _transcript_start_ts(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"timestamp"' not in line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                ts_raw = data.get("timestamp")
                if isinstance(ts_raw, str) and ts_raw:
                    try:
                        return datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        pass
        st = path.stat()
        return getattr(st, "st_birthtime", None) or st.st_mtime
    except OSError:
        return None


def sesion_inicio() -> float | None:
    """Timestamp de inicio de la sesión actual de central (transcripción más reciente de ~/central)."""
    env = os.environ.get("CENTRAL_SESSION_START")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    claude_home = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))
    slug = "-" + str(Path.home() / "central").lstrip("/").replace("/", "-")
    proj = claude_home / "projects" / slug
    if not proj.is_dir():
        proj = claude_home / "projects" / "-home-baudahn-central"
    if not proj.is_dir():
        return None
    try:
        files = [p for p in proj.glob("*.jsonl") if p.is_file()]
        if not files:
            return None
        newest = max(files, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return _transcript_start_ts(newest)


def _ts(ev: dict) -> float:
    try:
        return float(ev.get("ts", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _siguiente_libre(usados: set[str]) -> str:
    for cand in NOMBRES:
        if cand not in usados:
            return cand
    i = 1
    while f"agente-{i}" in usados:
        i += 1
    return f"agente-{i}"


def _nombres_explicitos(evs: list[dict]) -> set[str]:
    usados: set[str] = set()
    for ev in evs:
        tipo = ev.get("tipo")
        if tipo in ("decision", "lanzamiento", "terminado"):
            n = str(ev.get("nombre") or "").strip()
            if n and not LEGACY_ID_RE.match(n):
                usados.add(n)
        elif tipo in ("msg", "uso"):
            for k in ("de", "a", "agente"):
                n = str(ev.get(k) or "").strip()
                if n in _NOMBRES_SET:
                    usados.add(n)
    return usados


def alias_sesion(rows: Iterable[dict], since: float | None = None) -> dict[str, str]:
    """Mapa estable {id_viejo: nombre_griego} por orden de lanzamiento dentro de la sesión."""
    evs = [ev for ev in rows if since is None or _ts(ev) >= since]
    evs.sort(key=_ts)
    usados = _nombres_explicitos(evs)
    aliases: dict[str, str] = {}
    for ev in evs:
        if ev.get("tipo") not in ("decision", "lanzamiento"):
            continue
        n = str(ev.get("nombre") or "").strip()
        if n and LEGACY_ID_RE.match(n) and n not in aliases:
            elegido = _siguiente_libre(usados)
            aliases[n] = elegido
            usados.add(elegido)
    return aliases


def asignar(solicitado: str | None = None, ocupados: Iterable[str] = ()) -> str:
    """Asigna y reserva atómicamente el siguiente nombre libre de la sesión actual."""
    inicio = sesion_inicio()
    desde = inicio if inicio is not None else 0.0
    lock = home() / "nombres.lock"
    reg = home() / "nombres_sesion.json"
    with open(lock, "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        evs = sorted(eventos.leer(desde=desde), key=_ts)
        aliases = alias_sesion(evs)
        usados = _nombres_explicitos(evs) | set(aliases.values()) | {str(x).strip() for x in ocupados if str(x).strip()}
        try:
            data = json.loads(reg.read_text()) if reg.exists() else {}
        except (OSError, ValueError):
            data = {}
        reservados = data.get("reservados", []) if data.get("sesion") == desde else []
        for r in reservados:
            if n := str(r.get("nombre") or "").strip():
                usados.add(n)
        elegido = solicitado.strip() if solicitado and solicitado.strip() else _siguiente_libre(usados)
        if not any(r.get("nombre") == elegido for r in reservados):
            reservados.append({"nombre": elegido, "ts": time.time()})
        tmp = reg.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sesion": desde, "reservados": reservados}, ensure_ascii=False))
        tmp.replace(reg)
        return elegido


def resolver_log(nombre: str, subs_dir: Path) -> str:
    """Resuelve nombre griego o id viejo al stem de archivo de log correspondiente."""
    inicio = sesion_inicio()
    aliases = alias_sesion(eventos.leer(desde=inicio if inicio is not None else 0.0))
    rev = {v: k for k, v in aliases.items()}
    if nombre in rev and (subs_dir / f"{rev[nombre]}.log").exists():
        return rev[nombre]
    if (subs_dir / f"{nombre}.log").exists():
        return nombre
    return rev.get(nombre, nombre)
