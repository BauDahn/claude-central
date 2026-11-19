"""Funciones prefabricadas y carpetas de configuración (sin modelo ni backend).

  AGENT_STATION_ROLES     def. ~/.agent-station/roles
  AGENT_STATION_CONTEXTO  def. ~/.agent-station/contexto  (donde el optimizador deja INDEX.md y los mapas/docs)

Ejemplo de <rol>.toml:
  backend = "openai"                 # codex | openai | eco
  model = "gpt-5-mini"
  base_url = "https://api.openai.com/v1"   # cualquier API compatible con OpenAI
  api_key_env = "OPENAI_API_KEY"           # nombre de la variable; la clave NUNCA se guarda en archivos
"""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .home import home


def catalogo_modelos() -> list[dict]:
    return tomllib.loads((Path(__file__).parent / "modelos.toml").read_text()).get("modelo", [])


def modelo_por_id(ident: str) -> dict | None:
    return next((m for m in catalogo_modelos() if m["id"] == ident), None)


def roles_dir() -> Path:
    return Path(os.environ.get("AGENT_STATION_ROLES", home() / "roles")).expanduser()


def contexto_dir() -> Path:
    return Path(os.environ.get("AGENT_STATION_CONTEXTO", home() / "contexto")).expanduser()


@dataclass
class Rol:
    nombre: str
    prompt: str = ""
    opciones: dict = field(default_factory=dict)

    @property
    def backend(self) -> str:
        return self.opciones.get("backend", "codex")


PROMPTS = {
    "constructor": "Sos el que programa. Implementá tareas acotadas en el directorio de trabajo, verificá y respondé corto: archivos tocados y resultado.",
    "interfaz": "Diseñá e implementá interfaces claras, accesibles y coherentes con el producto. Verificá los cambios.",
    "diseno": "Analizá y proponé decisiones de diseño visual y de interacción, con razones concretas.",
    "orquestador": "Descomponé la tarea, proponé funciones/modelos adecuados y coordiná el trabajo sin lanzar agentes sin aprobación.",
    "optimizador": "Reducí contexto y costo sin perder información necesaria; actualizá mapas y documentación cuando corresponda.",
    "contextualizador": "Explorá el proyecto indicado y prepará un mapa breve y útil de su estructura y convenciones.",
    "revisor": "Revisá cambios buscando errores, regresiones y riesgos. Priorizá hallazgos concretos con archivo y línea.",
    "investigador": "Investigá la pregunta y presentá hallazgos verificables, separando hechos de inferencias.",
    "general": "Sos un asistente general, claro y breve. Respondés en español.",
    "gemini": "Sos un asistente general que analiza con cuidado y responde en español.",
    "gemini-constructor": "Implementá tareas acotadas dentro de src/ y tests/, verificá y respondé corto.",
}
BUILTIN = {n: Rol(n, p, {"escribir": n in ("constructor", "interfaz", "gemini-constructor")}) for n, p in PROMPTS.items()}


def cargar_rol(nombre: str) -> Rol:
    d = roles_dir()
    md, tm = d / f"{nombre}.md", d / f"{nombre}.toml"
    if not md.exists() and not tm.exists() and nombre in BUILTIN:
        return BUILTIN[nombre]
    if not md.exists() and not tm.exists():
        raise SystemExit(f"station: no existe el rol '{nombre}' (busqué {md} y {tm}). Mirá: station roles")
    prompt = md.read_text() if md.exists() else (BUILTIN[nombre].prompt if nombre in BUILTIN else "")
    opts = tomllib.loads(tm.read_text()) if tm.exists() else {}
    # Migración transparente: backend/model ya no se guardan en funciones.
    opts.pop("backend", None); opts.pop("model", None); opts.pop("modelo", None)
    return Rol(nombre, prompt, opts)


def listar_roles() -> list[Rol]:
    d = roles_dir()
    nombres = sorted({p.stem for p in d.glob("*.md")} | {p.stem for p in d.glob("*.toml")} | set(BUILTIN) if d.exists() else set(BUILTIN))
    return [cargar_rol(n) for n in nombres if not n.startswith("_")]
