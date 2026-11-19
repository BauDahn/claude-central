"""Adaptador de importación (solo lectura sobre el origen): trae al registro común lo que ya existe en la máquina.

  central  -> ~/agentes/estado/codex.jsonl (uso de Codex vía `cx`) y los mensajes entre sesiones de Claude Code
              guardados en ~/.claude/projects/*/*.jsonl (registros queue-operation).
Es idempotente: cada evento importado lleva `origen` (hash estable) y no se vuelve a insertar.
Es un adaptador opcional: el núcleo de central no depende de Claude Code ni de esta estructura de carpetas.
"""
import glob, hashlib, json, os, re
from pathlib import Path

from . import eventos

MSG = re.compile(r'<cross-session-message\b([^>]*)>\n?(.*?)\n?</cross-session-message>', re.S)
ATTR = re.compile(r'([\w-]+)="([^"]*)"')


def _h(*partes) -> str:
    return hashlib.sha1("|".join(map(str, partes)).encode()).hexdigest()[:16]


def _titulo(f: str) -> str:
    nombre = None
    with open(f, errors="ignore") as fh:
        for l in fh:
            if '"custom-title"' in l:
                try: nombre = json.loads(l).get("customTitle") or nombre
                except ValueError: pass
    return nombre or Path(f).parent.name.replace("-home-baudahn-", "").replace("-home-baudahn", "~")


def _ts(iso: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def desde_central(agentes_home: Path | None = None, claude_home: Path | None = None) -> dict:
    agentes_home = Path(agentes_home or os.environ.get("AGENTES_HOME", Path.home() / "agentes"))
    claude_home = Path(claude_home or os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))
    ya = {e["origen"] for e in eventos.leer() if "origen" in e}
    nuevos = {"uso": 0, "msg": 0}

    cx = agentes_home / "estado" / "codex.jsonl"
    if cx.exists():
        for l in cx.read_text(errors="ignore").splitlines():
            try: r = json.loads(l)
            except ValueError: continue
            o = _h("cx", r.get("ts"), r.get("hilo"), r.get("tarea", "")[:40])
            if o in ya: continue
            u = r.get("uso", {})
            eventos.registrar("uso", ts=r["ts"], origen=o, agente=f"{r.get('rol')}-codex", backend="codex", modelo=r.get("modelo"),
                              input=u.get("input", 0), cached=u.get("cached", 0), output=u.get("output", 0) + u.get("reasoning", 0),
                              seg=r.get("seg", 0), tarea=r.get("tarea", ""), resultado=r.get("resultado", ""), proyecto=r.get("proyecto"))
            ya.add(o); nuevos["uso"] += 1

    for f in glob.glob(str(claude_home / "projects" / "*" / "*.jsonl")):
        receptor = None
        with open(f, errors="ignore") as fh:
            for l in fh:
                if "cross-session-message" not in l or '"enqueue"' not in l: continue
                try: d = json.loads(l)
                except ValueError: continue
                if d.get("type") != "queue-operation" or d.get("operation") != "enqueue": continue
                m = MSG.search(d.get("content", ""))
                if not m: continue
                receptor = receptor or _titulo(f)
                a = dict(ATTR.findall(m[1])); cuerpo = m[2].strip(); ts = _ts(d["timestamp"])
                o = _h("cc", a.get("from-name"), receptor, cuerpo[:200], int(ts) // 10)
                if o in ya: continue
                eventos.registrar("msg", ts=ts, origen=o, de=a.get("from-name") or "?", a=receptor, cuerpo=cuerpo, backend="claude")
                ya.add(o); nuevos["msg"] += 1
    return nuevos
