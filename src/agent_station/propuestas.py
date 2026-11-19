"""Formato de propuestas interactivas emitidas por el agente principal."""
import json
import re

_BLOCK = re.compile(r"```propuesta\s*\n(.*?)\n```", re.S)


def parsear_bloque(texto: str) -> dict | None:
    m = _BLOCK.search(texto)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        return None
    required = ("id", "funcion", "modelo_recomendado", "motivo", "tarea")
    if not isinstance(data, dict) or any(not isinstance(data.get(k), str) or not data[k].strip() for k in required):
        return None
    if not isinstance(data.get("alternativas", []), list):
        return None
    return data


def quitar_bloque(texto: str) -> str:
    return _BLOCK.sub("", texto).strip()
