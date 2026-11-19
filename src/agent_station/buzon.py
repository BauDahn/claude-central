"""Buzón de mensajes entre agentes: igual para cualquier backend (un modelo, un script o una persona)."""
import re

from . import eventos

PREFIJOS = ("PEDIR-CONTEXTO", "CONTEXTO-LISTO", "NECESITA", "ASIGNA", "LISTO", "BLOQUEADO")


def enviar(de: str, a: str, cuerpo: str, **extra) -> dict:
    return eventos.registrar("msg", de=de, a=a, cuerpo=cuerpo.strip(), **extra)


def leer(agente: str | None = None, desde: float = 0.0) -> list[dict]:
    """Mensajes donde participa `agente` (emisor o receptor); todos si es None."""
    return [m for m in eventos.leer(desde, "msg") if agente in (None, m["a"], m["de"])]


def prefijo(cuerpo: str) -> str:
    return next((p for p in PREFIJOS if cuerpo.startswith(p)), "")


def tokens_declarados(valor: str) -> float | None:
    """'~1.1k' -> 1100. Para leer lo que el optimizador declara en CONTEXTO-LISTO."""
    m = re.fullmatch(r"~?\s*(\d+(?:[.,]\d+)?)\s*(k|m)?", valor.strip().lower())
    if not m:
        return None
    return float(m[1].replace(",", ".")) * {"k": 1e3, "m": 1e6, None: 1}[m[2]]
