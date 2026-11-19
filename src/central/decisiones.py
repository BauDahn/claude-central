"""Registro de decisiones de lanzamiento: qué prompt, qué motor/modelo se eligió, cómo salió y qué opinó el usuario.

Vive en el registro único de eventos (tipos decision, decision_resultado, decision_veredicto) y se exporta como
JSONL listo para entrenar un clasificador chico (p. ej. un modelo de ~270M) que elija motor/modelo.
"""
import hashlib, json, time
import uuid

from . import eventos


def registrar(prompt: str, motor: str, modelo: str = "", origen: str = "sub", directorio: str = "", nombre: str = "",
              motivo: str = "") -> str:
    id_ = uuid.uuid4().hex[:10]
    eventos.registrar("decision", id=id_, prompt=prompt, prompt_hash=hashlib.sha256(prompt.encode()).hexdigest()[:16],
                      motor=motor, modelo=modelo, origen=origen, directorio=directorio, nombre=nombre, motivo=motivo,
                      largo=len(prompt))
    return id_


def resultado(id_: str, estado: str, tokens: int = 0, seg: float = 0.0, hilo: str = "") -> None:
    eventos.registrar("decision_resultado", id=id_, estado=estado, tokens=tokens, seg=round(seg, 1), hilo=hilo or "")


def veredicto(id_: str, valor: int, nota: str = "") -> None:
    eventos.registrar("decision_veredicto", id=id_, valor=1 if valor > 0 else -1, nota=nota)


def unidas() -> list[dict]:
    """Una fila por decisión con su último resultado y veredicto."""
    filas: dict[str, dict] = {}
    for ev in eventos.leer():
        t, i = ev.get("tipo"), ev.get("id")
        if t == "decision": filas[i] = {**{k: v for k, v in ev.items() if k != "tipo"}, "estado": "corriendo", "tokens": None, "veredicto": None}
        elif t == "decision_resultado" and i in filas: filas[i].update(estado=ev["estado"], tokens=ev.get("tokens"), seg=ev.get("seg"), hilo=ev.get("hilo", ""))
        elif t == "decision_veredicto" and i in filas: filas[i]["veredicto"] = ev["valor"]
    return list(filas.values())


def por_hilo(hilo: str) -> dict | None:
    """Última decisión cuyo hilo (Codex) coincide: sirve para `central seguir`."""
    return next((f for f in reversed(unidas()) if f.get("hilo") == hilo), None)


def exportar(solo_con_veredicto: bool = False) -> str:
    """JSONL de entrenamiento: entrada = prompt; etiqueta = motor/modelo; bueno = terminó bien y el usuario no lo marcó mal."""
    out = []
    for f in unidas():
        if solo_con_veredicto and f["veredicto"] is None: continue
        bueno = f["estado"] == "terminado" and f["veredicto"] != -1
        out.append(json.dumps({"prompt": f["prompt"], "motor": f["motor"], "modelo": f["modelo"], "estado": f["estado"],
                               "tokens": f["tokens"], "veredicto": f["veredicto"], "bueno": bueno}, ensure_ascii=False))
    return "\n".join(out)
