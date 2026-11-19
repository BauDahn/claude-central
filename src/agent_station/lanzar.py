"""`station` sin argumentos: abre Claude Code (su interfaz de siempre) en la carpeta actual, ya configurado como agente PRINCIPAL.

Le agrega al sistema: qué es station, qué otras IAs/roles puede lanzar (`station correr`), las reglas de optimización y el
CONTEXTO COMPARTIDO de la carpeta (INDEX del optimizador). Deja pre-aprobados los comandos de [principal] en permisos.toml (def.: station seguro, python, pytest, agy);
`station permisos dar|quitar` siempre le pide permiso al usuario.
Lo demás (modelo, permisos, comandos /...) es Claude Code tal cual; los argumentos extra se le pasan directo (`station --model opus`).
"""
import os, shutil
from pathlib import Path

from . import contexto, permisos
from .home import home

HERRAMIENTAS = (Path(__file__).parent / "herramientas.md").read_text()


def sistema(cwd: Path) -> str:
    ctx = contexto.para_directorio(cwd)
    partes = [
        HERRAMIENTAS.strip(),
        "## CONTEXTO COMPARTIDO\n" + (contexto.texto(ctx) if ctx else "(no hay contexto cacheado para este directorio)"),
        f"Directorio de trabajo: {cwd}",
    ]
    return "\n\n".join(partes)


def comando(cwd: Path, extra: list[str]) -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("station: no encuentro Claude Code (`claude`). Instalalo: https://claude.com/claude-code")
    rest = extra
    archivo = home() / "principal-sistema.md"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(sistema(cwd))
    permitidos, denegados = permisos.reglas_principal()   # lista editable por el usuario en permisos.toml ([principal])
    cmd = [exe, "--append-system-prompt-file", str(archivo), "--allowedTools", ",".join(permitidos)]
    if denegados:
        cmd += ["--disallowedTools", ",".join(denegados)]
    return cmd + rest


def lanzar(extra: list[str]) -> None:
    cwd = Path.cwd().resolve()
    cmd = comando(cwd, extra)
    os.environ["AGENT_STATION_AGENTE"] = "principal"      # los subagentes que lance quedan registrados como delegados por él
    os.environ["AGENT_STATION_PROFUNDIDAD"] = "0"
    os.execv(cmd[0], cmd)
