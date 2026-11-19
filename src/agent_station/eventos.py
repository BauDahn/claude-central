"""Registro único de eventos (JSONL append-only con flock). Buzón, uso y bitácora son vistas de esto.

Cada línea es un objeto JSON con al menos: ts (epoch float), tipo ("msg" | "uso" | ...).
  msg: de, a, cuerpo            -> comunicación entre agentes (cualquier backend)
  uso: agente, backend, modelo, input, cached, output, seg, tarea, resultado, proyecto
"""
import fcntl, json, time
from pathlib import Path
from typing import Iterator

from .home import home


def archivo() -> Path:
    return home() / "eventos.jsonl"


def registrar(tipo: str, **campos) -> dict:
    ev = {"ts": campos.pop("ts", time.time()), "tipo": tipo, **campos}
    linea = json.dumps(ev, ensure_ascii=False) + "\n"
    with open(archivo(), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(linea)
    return ev


def leer(desde: float = 0.0, tipo: str | None = None) -> Iterator[dict]:
    f = archivo()
    if not f.exists():
        return
    with open(f, errors="ignore") as fh:
        for linea in fh:
            try:
                ev = json.loads(linea)
            except ValueError:
                continue
            if ev.get("ts", 0) >= desde and (tipo is None or ev.get("tipo") == tipo):
                yield ev
