"""Puente con el tablero de tareas (`agentes/bin/tareas`) y los bloqueos de archivo (`agentes/bin/bloqueo`).

Se maneja desde fuera del subagente (fuera de su sandbox): tomar la tarea antes de correr, y marcarla lista o bloqueada después.
"""
import os, subprocess
from pathlib import Path


def _bin(nombre: str) -> str:
    return str(Path(os.environ.get("AGENTES_HOME", Path.home() / "agentes")) / "bin" / nombre)


def _env(agente: str) -> dict:
    return dict(os.environ, AGENTE=agente, PATH=f"{Path.home()}/.local/bin:{os.environ.get('PATH', '')}")


def tomar(id_: str, agente: str, proyecto: str | None) -> str | None:
    """Devuelve un mensaje de error si no se pudo tomar la tarea, o None."""
    r = subprocess.run([_bin("tareas"), "tomar", id_, "--como", agente] + (["-p", proyecto] if proyecto else []),
                       env=_env(agente), capture_output=True, text=True)
    return None if r.returncode == 0 else (r.stdout + r.stderr).strip()


def cerrar(id_: str, agente: str, proyecto: str | None, texto: str) -> None:
    primera = texto.splitlines()[0] if texto else ""
    pr = ["-p", proyecto] if proyecto else []
    if primera.startswith("LISTO"):
        cmd = [_bin("tareas"), "listo", id_, "--nota", primera[:200]] + pr
    else:
        cmd = [_bin("tareas"), "bloquear", id_, "--motivo", primera[:200] or "sin mensaje final"] + pr
    subprocess.run(cmd, env=_env(agente), capture_output=True)


def soltar_bloqueos(agente: str) -> None:
    subprocess.run([_bin("bloqueo"), "soltar-todo", "--como", agente], env=_env(agente),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
