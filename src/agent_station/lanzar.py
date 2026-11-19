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


def sistema(cwd: Path, voz: bool = False, interactivo: bool = False) -> str:
    ctx = contexto.para_directorio(cwd)
    partes = [
        HERRAMIENTAS.strip(),
        "## CONTEXTO COMPARTIDO\n" + (contexto.texto(ctx) if ctx else "(no hay contexto cacheado para este directorio)"),
        f"Directorio de trabajo: {cwd}",
    ]
    if voz or interactivo:
        from .voz.motor import instrucciones_interactivo, instrucciones_voz
        partes.append(instrucciones_voz())
        if interactivo:
            partes.append(instrucciones_interactivo())
    return "\n\n".join(partes)


def _extraer_flags_voz(extra: list[str]) -> tuple[list[str], bool, bool]:
    voz = os.environ.get("AGENT_STATION_VOZ") == "1"
    interactivo = os.environ.get("AGENT_STATION_INTERACTIVO") == "1"
    rest = []
    for arg in extra:
        if arg == "--voz":
            voz = True
        elif arg == "--interactivo":
            voz = True
            interactivo = True
        else:
            rest.append(arg)
    return rest, voz, interactivo


def comando(cwd: Path, extra: list[str]) -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("station: no encuentro Claude Code (`claude`). Instalalo: https://claude.com/claude-code")
    rest, voz, interactivo = _extraer_flags_voz(extra)
    archivo = home() / "principal-sistema.md"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(sistema(cwd, voz=voz, interactivo=interactivo))
    permitidos, denegados = permisos.reglas_principal()   # lista editable por el usuario en permisos.toml ([principal])
    cmd = [exe, "--append-system-prompt-file", str(archivo), "--allowedTools", ",".join(permitidos)]
    if denegados:
        cmd += ["--disallowedTools", ",".join(denegados)]
    if (voz or interactivo) and "--settings" not in rest:
        from .voz.cli_voz import hooks_settings_path
        cmd += ["--settings", str(hooks_settings_path())]
    return cmd + rest


def lanzar(extra: list[str]) -> None:
    cwd = Path.cwd().resolve()
    _, voz, interactivo = _extraer_flags_voz(extra)
    if voz:
        os.environ["AGENT_STATION_VOZ"] = "1"
    if interactivo:
        os.environ["AGENT_STATION_INTERACTIVO"] = "1"
    cmd = comando(cwd, extra)
    os.environ["AGENT_STATION_AGENTE"] = "principal"      # los subagentes que lance quedan registrados como delegados por él
    os.environ["AGENT_STATION_PROFUNDIDAD"] = "0"
    os.execv(cmd[0], cmd)
