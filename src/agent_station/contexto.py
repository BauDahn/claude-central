"""Contexto compartido (lo que mantiene el optimizador): INDEX.md con una línea por entrada
`ruta | fuente | fecha | ~tokens | resumen`. El ejecutor lo consulta ANTES de lanzar al agente, así la regla
"no leas el repo entero si ya hay un mapa" no depende de que el modelo se acuerde de cumplirla."""
from dataclasses import dataclass
from pathlib import Path

from .config import contexto_dir


@dataclass
class Entrada:
    ruta: Path
    fuente: str
    fecha: str
    tokens: str
    resumen: str


def indice() -> list[Entrada]:
    idx = contexto_dir() / "INDEX.md"
    if not idx.exists():
        return []
    out = []
    for l in idx.read_text(errors="ignore").splitlines():
        if l.startswith("#") or l.count("|") < 4:
            continue
        c = [x.strip() for x in l.split("|", 4)]
        out.append(Entrada(contexto_dir() / c[0], c[1], c[2], c[3], c[4]))
    return out


def para_directorio(cwd: Path) -> list[Entrada]:
    """Entradas cuya fuente es este directorio (o un subdirectorio/archivo de él) y cuyo archivo existe."""
    cwd = cwd.expanduser().resolve()
    res = []
    for e in indice():
        if not e.ruta.exists():
            continue
        for tok in e.fuente.replace(",", " ").split():
            p = Path(tok.strip("()")).expanduser()
            if p.is_absolute() and (cwd == p.resolve() or cwd in p.resolve().parents or p.resolve() in cwd.parents):
                res.append(e)
                break
    return res


def texto(entradas: list[Entrada], max_chars: int = 24000) -> str:
    partes, total = [], 0
    for e in entradas:
        t = e.ruta.read_text(errors="ignore")
        if total + len(t) > max_chars:
            partes.append(f"[contexto omitido por tamaño: {e.ruta} ({e.tokens})]")
            continue
        partes.append(f"### {e.ruta.name}  (fuente: {e.fuente}, {e.fecha})\n{t}")
        total += len(t)
    return "\n\n".join(partes)
