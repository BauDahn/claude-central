"""Permisos por rol. Perfiles en permisos.toml (por defecto el del paquete; el tuyo en AGENT_STATION_PERMISOS o
~/.agent-station/permisos.toml reemplaza perfil por perfil) + concesiones temporales en permisos-estado.json.

Los backends traducen el Perfil a sus flags (Claude: allowed/disallowed tools y permission-mode; Codex: sandbox; agy: --mode).
"""
import json, os, re, time, tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import eventos
from .home import home

DEFECTO = Path(__file__).parent / "permisos.toml"
PRINCIPAL = ("principal", "central")      # nombres que NO se pueden tocar con `dar`/`quitar`
SEGURAS_STATION = ["correr", "proponer", "aprobar", "rechazar", "roles", "modelos", "bitacora", "uso", "optimizador", "msg", "permisos ver"]


@dataclass
class Perfil:
    nombre: str
    modo: str = "lectura"                       # lectura | editar
    permitir: list[str] = field(default_factory=list)
    denegar: list[str] = field(default_factory=list)
    rutas: list[str] = field(default_factory=list)

    @property
    def edita(self) -> bool:
        return self.modo == "editar"

    def instrucciones(self) -> str:
        """Texto para el prompt: refuerzo blando para los backends que no pueden hacer cumplir rutas/denegar."""
        if not self.edita:
            return "Tu perfil es de SOLO LECTURA: no edites ni crees archivos ni corras comandos que cambien algo."
        l = ["Tu perfil permite editar archivos."]
        if self.rutas: l.append("Solo podés editar dentro de: " + ", ".join(self.rutas) + ".")
        if self.denegar: l.append("Tenés prohibido: " + ", ".join(self.denegar) + ".")
        return " ".join(l)


def archivo_perfiles() -> Path:
    return Path(os.environ.get("AGENT_STATION_PERMISOS", home() / "permisos.toml")).expanduser()


def archivo_estado() -> Path:
    return home() / "permisos-estado.json"


def _leer_toml(p: Path) -> dict:
    try: return tomllib.loads(p.read_text())
    except OSError: return {}
    except ValueError as e: raise SystemExit(f"station: {p} no es un TOML válido: {e}")


def tabla() -> dict:
    """Perfiles efectivos: los del paquete, reemplazados perfil por perfil por los del usuario."""
    return {**_leer_toml(DEFECTO), **_leer_toml(archivo_perfiles())}


def _base(nombre: str) -> Perfil:
    t = tabla()
    d = t.get(nombre) or t.get("general") or {}
    modo = d.get("modo", "lectura")
    return Perfil(nombre if nombre in t else "general", modo if modo in ("lectura", "editar") else "lectura",
                  list(d.get("permitir", [])), list(d.get("denegar", [])), list(d.get("rutas", [])))


# ---- vencimientos y concesiones ----

def parsear_hasta(s: str, ahora: float | None = None) -> float | None:
    """'30m' | '1h' | '2d' -> epoch de vencimiento; 'siempre' -> None."""
    if s == "siempre": return None
    m = re.fullmatch(r"(\d+)([mhd])", s)
    if not m: raise SystemExit(f"station: duración inválida '{s}' (usá 30m, 1h, 2d o siempre)")
    return (time.time() if ahora is None else ahora) + int(m[1]) * {"m": 60, "h": 3600, "d": 86400}[m[2]]


def _estado() -> list[dict]:
    try: c = json.loads(archivo_estado().read_text()).get("concesiones", [])
    except (OSError, ValueError): return []
    ahora = time.time()
    return [x for x in c if x.get("hasta") is None or x["hasta"] > ahora]


def _guardar(c: list[dict]) -> None:
    archivo_estado().write_text(json.dumps({"concesiones": c}, ensure_ascii=False, indent=1))


def concesiones(rol: str | None = None) -> list[dict]:
    return [c for c in _estado() if rol is None or c["rol"] == rol]


def _por() -> str:
    return os.environ.get("AGENT_STATION_AGENTE", "usuario")


def dar(rol: str, regla: str, hasta: str = "1h") -> dict:
    if rol in PRINCIPAL:
        raise SystemExit("station: el agente principal no puede recibir permisos por este medio; sus permisos los definís vos en permisos.toml ([principal]).")
    if int(os.environ.get("AGENT_STATION_PROFUNDIDAD", "0")) > 0:
        raise SystemExit("station: un subagente no puede dar permisos.")
    if not regla.strip(): raise SystemExit("station: regla vacía.")
    c = {"rol": rol, "regla": regla.strip(), "hasta": parsear_hasta(hasta), "creado": time.time(), "por": _por()}
    _guardar([x for x in _estado() if not (x["rol"] == rol and x["regla"] == c["regla"])] + [c])
    eventos.registrar("permiso", accion="dar", agente=rol, rol=rol, regla=c["regla"], hasta=c["hasta"], por=c["por"])
    return c


def quitar(rol: str, regla: str) -> int:
    if rol in PRINCIPAL:
        raise SystemExit("station: los permisos del agente principal se editan en permisos.toml.")
    if int(os.environ.get("AGENT_STATION_PROFUNDIDAD", "0")) > 0:
        raise SystemExit("station: un subagente no puede quitar permisos.")
    antes = _estado()
    c = [x for x in antes if not (x["rol"] == rol and x["regla"] == regla.strip())]
    if len(c) != len(antes):
        _guardar(c)
        eventos.registrar("permiso", accion="quitar", agente=rol, rol=rol, regla=regla.strip(), por=_por())
    return len(antes) - len(c)


# ---- perfil efectivo de un rol ----

def perfil_de(nombre: str, escribir: bool | None = None) -> Perfil:
    """Perfil base + concesiones vigentes. `escribir=False` baja a lectura; `escribir=True` NO sube el perfil."""
    p = _base(nombre)
    for c in concesiones(nombre):
        if c["regla"] == "editar": p = replace(p, modo="editar")
        elif c["regla"] not in p.permitir: p = replace(p, permitir=p.permitir + [c["regla"]])
    if escribir is False: p = replace(p, modo="lectura")
    return p


def perfil_rol(rol) -> Perfil:
    """Perfil de un Rol (config.Rol): el ya resuelto por el ejecutor (opciones['_perfil']) o el calculado ahora."""
    return rol.opciones.get("_perfil") or perfil_de(rol.nombre, rol.opciones.get("escribir") if rol.opciones.get("escribir") is False else None)


def reglas_claude(p: Perfil) -> dict:
    """Perfil -> flags de Claude Code: {'allowed': [...], 'disallowed': [...], 'modo': 'acceptEdits' | None}."""
    allowed, disallowed, modo = list(p.permitir), list(p.denegar), None
    if p.edita and p.rutas:
        for r in p.rutas:
            g = r.rstrip("/") + "/**"
            allowed += [f"Edit({g})", f"Write({g})"]
        disallowed += ["NotebookEdit"]
    elif p.edita: modo = "acceptEdits"
    else: disallowed += ["Edit", "Write", "NotebookEdit"]
    return {"allowed": allowed, "disallowed": disallowed, "modo": modo}


# ---- agente principal ----

def principal() -> dict:
    d = tabla().get("principal", {})
    return {"comandos": list(d.get("comandos", ["station", "python", "pytest", "agy"])), "denegar": list(d.get("denegar", []))}


def reglas_principal() -> tuple[list[str], list[str]]:
    """Lista editable de comandos del principal -> reglas Bash(...) para `--allowedTools` / `--disallowedTools`."""
    cfg, allowed = principal(), []
    for c in cfg["comandos"]:
        c = c.strip()
        if not c: continue
        if c == "station": allowed += [f"Bash(station {s}:*)" for s in SEGURAS_STATION]
        elif c.startswith("Bash("): allowed.append(c)
        else: allowed.append(f"Bash({c}:*)")
    return allowed, cfg["denegar"]


def describir(rol: str) -> str:
    p = perfil_de(rol)
    l = [f"{rol}: perfil '{p.nombre}' · modo {p.modo}" + (f" · rutas {', '.join(p.rutas)}" if p.rutas else "")]
    if p.permitir: l.append("  permitir: " + ", ".join(p.permitir))
    if p.denegar: l.append("  denegar:  " + ", ".join(p.denegar))
    for c in concesiones(rol):
        v = "siempre" if c["hasta"] is None else "hasta " + time.strftime("%m-%d %H:%M", time.localtime(c["hasta"]))
        l.append(f"  + concedido: {c['regla']} ({v}, por {c.get('por', '?')})")
    return "\n".join(l)
