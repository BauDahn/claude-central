"""Registro de consumo común a todos los backends (mismo formato para Claude, Codex u otra API)."""
from . import eventos


def reiniciar() -> dict:
    """Marca un nuevo punto de inicio para los resúmenes de consumo."""
    return eventos.registrar("uso_reset")


def registrar(agente: str, backend: str, modelo: str, entrada: int = 0, cache: int = 0, salida: int = 0,
              seg: float = 0, tarea: str = "", resultado: str = "", proyecto: str | None = None, **extra) -> dict:
    return eventos.registrar("uso", agente=agente, backend=backend, modelo=modelo, input=entrada, cached=cache,
                             output=salida, seg=seg, tarea=tarea[:300], resultado=resultado[:200], proyecto=proyecto, **extra)


def resumen(desde: float = 0.0, por: str = "backend") -> dict[str, dict]:
    tot: dict[str, dict] = {}
    reinicios = eventos.leer(0.0, "uso_reset")
    inicio = max(desde, max((e["ts"] for e in reinicios), default=0.0))
    for u in eventos.leer(inicio, "uso"):
        t = tot.setdefault(str(u.get(por) or "?"), {"tareas": 0, "input": 0, "cached": 0, "output": 0, "seg": 0})
        t["tareas"] += 1
        for k in ("input", "cached", "output", "seg"):
            t[k] += u.get(k, 0)
    return tot
