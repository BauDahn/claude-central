"""Supervisor liviano de subagentes (`sub`): detecta inactivos, terminados sin reportar y resultados genéricos/vacíos."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import eventos, nombres

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
CURSOR_NL_RE = re.compile(r"\x1b\[\d*(?:;\d+)*[Hf]|\x1b\[\d*[ABG]|\r")
BUS_LINE_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+\[([^\]]+)\]\s*(.*)$")
SCRIPT_START_RE = re.compile(r'^Script iniciado en .*?\[COMMAND="(.*)"\]$')
SCRIPT_END_RE = re.compile(r'^Script terminado en .*?\[CÓDIGO_SALIDA_ORDEN="(-?\d+)"\]$')

INICIA_RE = re.compile(r"^inicia \(")
TERMINO_RE = re.compile(r"^terminó \(código (-?\d+)\)")
FIN_RE = re.compile(
    r"^(?:\[[^\]]+\]\s*)?(?:listo|finalizado|terminado|completado|hecho|bloqueado|necesita|error|fall[oó]|resumen)\b",
    re.I,
)
GENERICO_RE = re.compile(
    r"^(?:listo|hecho|terminado|completado|finalizado|ok|vale|done|sin cambios|todo bien|nada que hacer)\.?$",
    re.I,
)
ERROR_CRUDO_RE = re.compile(
    r"\b(?:rate limit|quota exceeded|command not found|traceback \(most recent call last\)|lorem ipsum)\b",
    re.I,
)
TUI_RUIDO_RE = re.compile(
    r"^(?:[─━═\-•○●⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷]+|\?\s*for shortcuts.*|>\s*(?:Accept-edits mode.*)?|"
    r"esc to cancel.*|Working\s*\(.*|Running command.*|Generating\.\.\.|Accessing workspace:.*|"
    r"Tip: Use /tasks.*|Starting MCP servers.*|›\s*Ask Codex.*|←\s*for agents.*|"
    r"Worked for \d+.*|COORDINACIÓN:\s*sos un subagente.*)$",
    re.I,
)
REPOSO_RE = re.compile(
    r"(?:Worked for \d+[ms]|›\s*Ask Codex to do anything|\?\s*for shortcuts)",
    re.I,
)


@dataclass
class SubEstado:
    nombre: str
    alias: str | None = None
    motor: str = "?"
    modelo: str = ""
    directorio: str = ""
    inicio_ts: float = 0.0
    vivo: bool = False
    cpu_pct: float = 0.0
    pids: list[int] = field(default_factory=list)
    log_path: Path | None = None
    log_mtime: float | None = None
    termino_rc: int | None = None
    prompt_en_reposo: bool = False
    lineas_utiles: list[str] = field(default_factory=list)
    reportes_agente: list[tuple[float, str]] = field(default_factory=list)
    reporto_fin: bool = False
    ultimo_reporte_ts: float = 0.0
    alertas: list[dict] = field(default_factory=list)

    @property
    def etiqueta(self) -> str:
        return f"{self.alias} ({self.nombre})" if self.alias else self.nombre


def agentes_dir(base: Path | None = None) -> Path:
    return Path(base or os.environ.get("AGENTES_HOME", Path.home() / "agentes")).expanduser()


def _limpiar_lineas(raw: str) -> tuple[list[str], int | None, bool]:
    """Normaliza secuencias ANSI/TUI a líneas legibles, extrae código de salida y detecta prompt en reposo."""
    texto = CURSOR_NL_RE.sub("\n", raw)
    texto = ANSI_RE.sub("", texto)
    rc: int | None = None
    limpias: list[str] = []
    for linea in texto.splitlines():
        s = linea.strip()
        if not s:
            continue
        if SCRIPT_START_RE.match(s):
            continue
        if m := SCRIPT_END_RE.match(s):
            rc = int(m[1])
            continue
        limpias.append(s)
    cola = "\n".join(limpias[-12:])
    reposo = bool(REPOSO_RE.search(cola)) and not any(
        k in cola for k in ("Working (", "Generating...", "Running command")
    )
    return limpias, rc, reposo


def _filtrar_utiles(lineas: list[str], prompt_txt: str = "") -> list[str]:
    """Descarta cromado de TUI y eco del prompt inicial para medir sustancia real del resultado."""
    frag_prompt = {l.strip()[:60] for l in prompt_txt.splitlines() if len(l.strip()) >= 12}
    out = []
    for l in lineas:
        if len(l) <= 2 or TUI_RUIDO_RE.match(l):
            continue
        if any(l.startswith(f) or f in l for f in frag_prompt):
            continue
        out.append(l)
    return out


def _reconstruir_ts(hhmmss: str, ahora: float, inicio_ts: float | None = None) -> float:
    """Convierte HH:MM:SS de bus.log a epoch manejando cruce de medianoche."""
    h, m, s = map(int, hhmmss.split(":"))
    base = dt.datetime.fromtimestamp(ahora)
    cand = base.replace(hour=h, minute=m, second=s, microsecond=0).timestamp()
    if cand > ahora + 120:
        cand -= 86400
    if inicio_ts and cand < inicio_ts - 120 and cand + 86400 <= ahora + 120:
        cand += 86400
    return cand


def _canonizar(etiqueta: str, aliases: dict[str, str], stems: set[str]) -> str:
    rev = {v: k for k, v in aliases.items()}
    if etiqueta in stems:
        return etiqueta
    if etiqueta in rev and rev[etiqueta] in stems:
        return rev[etiqueta]
    return rev.get(etiqueta, etiqueta)


def leer_procesos_ps() -> dict[str, dict]:
    """Inspecciona procesos vivos asociados a logs `subs/<nombre>.log` y suma CPU de su árbol."""
    r = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,pcpu=,args="],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if r.returncode != 0:
        return {}
    procs: dict[int, tuple[int, float, str]] = {}
    hijos: dict[int, list[int]] = {}
    for linea in r.stdout.splitlines():
        partes = linea.strip().split(None, 3)
        if len(partes) < 4:
            continue
        try:
            pid, ppid, cpu = int(partes[0]), int(partes[1]), float(partes[2].replace(",", "."))
        except ValueError:
            continue
        procs[pid] = (ppid, cpu, partes[3])
        hijos.setdefault(ppid, []).append(pid)

    log_pat = re.compile(r"/subs/([^\s/']+)\.log\b")
    raices: dict[str, set[int]] = {}
    for pid, (_, _, args) in procs.items():
        if m := log_pat.search(args):
            raices.setdefault(m[1], set()).add(pid)

    res: dict[str, dict] = {}
    for nombre, seeds in raices.items():
        visitados: set[int] = set()
        pila = list(seeds)
        while pila:
            cur = pila.pop()
            if cur in visitados:
                continue
            visitados.add(cur)
            pila.extend(hijos.get(cur, ()))
        cpu_total = sum(procs[p][1] for p in visitados if p in procs)
        res[nombre] = {"vivo": True, "cpu_pct": round(cpu_total, 2), "pids": sorted(visitados)}
    return res


def _es_reporte_generico(reporte: str) -> bool:
    cuerpo = re.sub(r"^\[[^\]]+\]\s*", "", reporte).strip()
    if not cuerpo:
        return True
    if GENERICO_RE.match(cuerpo):
        return True
    return len(cuerpo) < 15 and not any(ch.isdigit() or ch in "/." for ch in cuerpo)


def inspeccionar(
    agentes_home: Path | None = None,
    desde_seg: float = 86400.0,
    umbral_inactivo_min: float = 10.0,
    umbral_avance_min: float = 5.0,
    cpu_umbral: float = 1.5,
    ahora: float | None = None,
    procesos_fn: Callable[[], dict[str, dict]] | None = None,
) -> list[SubEstado]:
    """Analiza subs.json, bus.log, subs/*.log y procesos para detectar subagentes con problemas."""
    home_ag = agentes_dir(agentes_home)
    subs_dir = home_ag / "estado" / "subs"
    reg_path = home_ag / "estado" / "subs.json"
    bus_path = subs_dir / "bus.log"
    now = ahora if ahora is not None else time.time()

    try:
        reg = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    except (OSError, ValueError):
        reg = {}

    stems = set(reg.keys())
    if subs_dir.is_dir():
        stems |= {p.stem for p in subs_dir.glob("*.log") if p.name != "bus.log"}

    inicio_ses = nombres.sesion_inicio()
    aliases = nombres.alias_sesion(
        eventos.leer(desde=inicio_ses if inicio_ses is not None else 0.0)
    )
    procs = (procesos_fn or leer_procesos_ps)()

    bus_por_sub: dict[str, list[tuple[float, str]]] = {}
    if bus_path.exists():
        for raw in bus_path.read_text(errors="ignore").splitlines():
            if not (m := BUS_LINE_RE.match(raw)):
                continue
            stem = _canonizar(m[2].strip(), aliases, stems)
            ini = float(reg.get(stem, {}).get("ts") or 0) or None
            ts = _reconstruir_ts(m[1], now, ini)
            bus_por_sub.setdefault(stem, []).append((ts, m[3].strip()))

    resultados: list[SubEstado] = []
    for nombre in sorted(stems):
        meta = reg.get(nombre, {})
        log_path = subs_dir / f"{nombre}.log"
        prompt_path = subs_dir / f"{nombre}.prompt"
        inicio = float(meta.get("ts") or 0)
        if not inicio and log_path.exists():
            inicio = log_path.stat().st_ctime
        if now - inicio > desde_seg:
            continue

        proc = procs.get(nombre, {})
        vivo = bool(proc.get("vivo", False))
        cpu_pct = float(proc.get("cpu_pct", 0.0))

        raw_log = log_path.read_text(errors="ignore") if log_path.exists() else ""
        lineas_limpias, rc_log, reposo = _limpiar_lineas(raw_log)
        prompt_txt = prompt_path.read_text(errors="ignore") if prompt_path.exists() else ""
        utiles = _filtrar_utiles(lineas_limpias, prompt_txt)
        log_mtime = log_path.stat().st_mtime if log_path.exists() else None

        msgs = bus_por_sub.get(nombre, [])
        termino_rc = rc_log
        reportes_agente: list[tuple[float, str]] = []
        for ts, txt in msgs:
            if INICIA_RE.match(txt):
                continue
            if mt := TERMINO_RE.match(txt):
                if termino_rc is None:
                    termino_rc = int(mt[1])
                continue
            reportes_agente.append((ts, txt))

        if termino_rc is not None:
            vivo = False
        reporto_fin = any(FIN_RE.match(txt) for _, txt in reportes_agente)
        ult_rep = reportes_agente[-1][0] if reportes_agente else inicio

        est = SubEstado(
            nombre=nombre,
            alias=aliases.get(nombre),
            motor=str(meta.get("motor") or "?"),
            modelo=str(meta.get("modelo") or ""),
            directorio=str(meta.get("dir") or ""),
            inicio_ts=inicio,
            vivo=vivo,
            cpu_pct=cpu_pct,
            pids=list(proc.get("pids", [])),
            log_path=log_path if log_path.exists() else None,
            log_mtime=log_mtime,
            termino_rc=termino_rc,
            prompt_en_reposo=reposo,
            lineas_utiles=utiles,
            reportes_agente=reportes_agente,
            reporto_fin=reporto_fin,
            ultimo_reporte_ts=ult_rep,
        )

        min_sin_rep = max(0.0, (now - ult_rep) / 60.0)
        min_sin_log = max(0.0, (now - log_mtime) / 60.0) if log_mtime else min_sin_rep

        if vivo and not reporto_fin and min_sin_rep >= umbral_inactivo_min and cpu_pct <= cpu_umbral:
            if min_sin_log >= umbral_avance_min or reposo:
                motivo = "prompt en reposo" if reposo else f"log sin cambios {min_sin_log:.0f}m"
                est.alertas.append({
                    "tipo": "inactivo",
                    "mensaje": f"lleva {min_sin_rep:.0f}m sin reportar, CPU {cpu_pct:.1f}% y sin avance ({motivo})",
                })

        if not vivo and (now - inicio) > 15:
            if not reportes_agente:
                extra = f" (código {termino_rc})" if termino_rc is not None else ""
                est.alertas.append({
                    "tipo": "termino_sin_reportar",
                    "mensaje": f"terminó{extra} sin ningún reporte en bus.log",
                })
            elif not reporto_fin:
                extra = f" (código {termino_rc})" if termino_rc is not None else ""
                est.alertas.append({
                    "tipo": "termino_sin_reportar",
                    "mensaje": f"terminó{extra} tras {len(reportes_agente)} avance(s) sin reporte final",
                })

        if not vivo or reporto_fin or reposo:
            razones = []
            if reportes_agente and _es_reporte_generico(reportes_agente[-1][1]):
                razones.append(f"reporte genérico ({reportes_agente[-1][1]!r})")
            chars_utiles = sum(len(l) for l in utiles)
            bus_sustantivo = reporto_fin and bool(reportes_agente) and not _es_reporte_generico(reportes_agente[-1][1])
            if log_path.exists() and (chars_utiles < 40 or (len(utiles) < 2 and not bus_sustantivo)):
                razones.append(f"salida vacía o mínima ({len(utiles)} líneas, {chars_utiles} chars)")
            cola_txt = "\n".join(utiles[-8:])
            if ERROR_CRUDO_RE.search(cola_txt) and not reporto_fin:
                razones.append("error sin cierre en la salida")
            if razones:
                est.alertas.append({
                    "tipo": "resultado_generico",
                    "mensaje": "resultado parece genérico o vacío: " + "; ".join(razones),
                })

        resultados.append(est)
    return resultados


def notificar_alertas(
    estados: list[SubEstado],
    agentes_home: Path | None = None,
    ahora: float | None = None,
    repetir: bool = False,
) -> list[dict]:
    """Escribe alertas nuevas en bus.log (`reportar`) y avisos.log, deduplicando por ejecución."""
    home_ag = agentes_dir(agentes_home)
    subs_dir = home_ag / "estado" / "subs"
    bus_path = subs_dir / "bus.log"
    avisos_path = home_ag / "estado" / "avisos.log"
    estado_path = subs_dir / "supervisor_estado.json"
    now = ahora if ahora is not None else time.time()

    try:
        vistos = json.loads(estado_path.read_text()) if estado_path.exists() else {}
    except (OSError, ValueError):
        vistos = {}

    emitidas: list[dict] = []
    hora = dt.datetime.fromtimestamp(now).strftime("%H:%M:%S")
    fecha_hora = dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")

    nuevas_bus = []
    nuevos_avisos = []
    for est in estados:
        for al in est.alertas:
            clave = f"{est.nombre}:{int(est.inicio_ts)}:{al['tipo']}"
            if not repetir and clave in vistos:
                continue
            texto = f"ALERTA [{al['tipo']}] {est.etiqueta}: {al['mensaje']}"
            nuevas_bus.append(f"{hora} [supervisor] {texto}\n")
            nuevos_avisos.append(f"{fecha_hora} [supervisor] {texto}\n")
            vistos[clave] = now
            emitidas.append({"sub": est.etiqueta, **al, "texto": texto})

    if nuevas_bus:
        subs_dir.mkdir(parents=True, exist_ok=True)
        with bus_path.open("a", encoding="utf-8") as fh:
            fh.writelines(nuevas_bus)
        with avisos_path.open("a", encoding="utf-8") as fh:
            fh.writelines(nuevos_avisos)
        tmp = estado_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(vistos, indent=2, ensure_ascii=False))
        tmp.replace(estado_path)

    return emitidas


def _parse_desde(s: str) -> float:
    m = re.fullmatch(r"(\d+)([mhd])", s.strip())
    if not m:
        raise SystemExit(f"central supervisar: formato inválido --desde '{s}' (usá ej. 30m, 12h, 2d)")
    return int(m[1]) * {"m": 60, "h": 3600, "d": 86400}[m[2]]


def cmd_supervisar(a: argparse.Namespace) -> int:
    estados = inspeccionar(
        desde_seg=_parse_desde(a.desde),
        umbral_inactivo_min=a.umbral_inactivo,
        umbral_avance_min=a.umbral_avance,
        cpu_umbral=a.cpu,
    )
    emitidas = [] if a.solo_ver else notificar_alertas(estados, repetir=a.repetir)
    if a.json:
        payload = [
            {
                "nombre": e.nombre,
                "alias": e.alias,
                "motor": e.motor,
                "vivo": e.vivo,
                "cpu_pct": e.cpu_pct,
                "reportes": len(e.reportes_agente),
                "reporto_fin": e.reporto_fin,
                "alertas": e.alertas,
            }
            for e in estados
        ]
        print(json.dumps({"subagentes": payload, "emitidas": emitidas}, indent=2, ensure_ascii=False))
        return 0

    if not estados:
        print(f"(sin subagentes en las últimas {a.desde})")
        return 0
    for e in estados:
        estado_txt = "vivo" if e.vivo else "cerrado"
        print(
            f"{e.etiqueta:<26} {estado_txt:<8} {e.motor:<7} cpu={e.cpu_pct:4.1f}% "
            f"rep={len(e.reportes_agente)} fin={'sí' if e.reporto_fin else 'no'}"
        )
        for al in e.alertas:
            print(f"  ! [{al['tipo']}] {al['mensaje']}")
    if a.solo_ver:
        print(f"\n(solo-ver: {sum(len(e.alertas) for e in estados)} alerta(s) detectadas, sin escribir en bus.log)")
    else:
        print(f"\n({len(emitidas)} alerta(s) nuevas emitidas en bus.log y avisos.log)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="central supervisar")
    ap.add_argument("--desde", default="24h")
    ap.add_argument("--umbral-inactivo", type=float, default=10.0)
    ap.add_argument("--umbral-avance", type=float, default=5.0)
    ap.add_argument("--cpu", type=float, default=1.5)
    ap.add_argument("--solo-ver", action="store_true", help="no escribe en bus.log/avisos.log ni guarda estado")
    ap.add_argument("--repetir", action="store_true", help="re-emite alertas ya notificadas")
    ap.add_argument("--json", action="store_true")
    return cmd_supervisar(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
