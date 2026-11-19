"""central — CLI de central.

  central                                  abre (o enfoca) la ventana del Claude principal
  central principal [flags de claude]      Claude Code en esta carpeta como agente PRINCIPAL (con central, roles y reglas de optimización)
  central ver [grafo|logs|uso]             visor del grafo de comunicación, logs y uso por IA

  central msg enviar <de> <a> "texto"      escribe un mensaje en el buzón (cualquier agente, cualquier backend)
  central msg leer [agente] [--desde 2d]
  central bitacora [--desde 24h] [--agente X] [--completo] [--seguir]
  central optimizador [--desde 7d]         qué logró el optimizador (pedidos, entregas, tokens ahorrados)
  central uso [--desde 7d] [--por backend|agente|modelo|proyecto]
  central permisos ver [rol] | dar <rol> <regla> [--hasta 1h] | quitar <rol> <regla>   permisos por agente (solo subagentes)
  central importar central                trae a este registro lo que ya existe en la máquina (Codex vía el antiguo cx, sesiones Claude)
"""
import argparse, datetime as dt, os, re, sys, time, uuid
from pathlib import Path

from . import tablero, decisiones, buzon, config, ejecutor, eventos, importar, lanzar, permisos, uso


def desde_ts(s: str) -> float:
    m = re.fullmatch(r"(\d+)([mhd])", s)
    if m: return time.time() - int(m[1]) * {"m": 60, "h": 3600, "d": 86400}[m[2]]
    return dt.datetime.fromisoformat(s).timestamp()


def fmt(ev: dict, completo: bool) -> str:
    t = dt.datetime.fromtimestamp(ev["ts"]).strftime("%m-%d %H:%M:%S")
    if ev["tipo"] == "msg":
        txt = ev["cuerpo"] if completo else " ".join(ev["cuerpo"].split())
        if not completo and len(txt) > 220: txt = txt[:220] + "…"
        return f"{t}  {ev['de']} → {ev['a']}  {txt}"
    if ev["tipo"] == "uso":
        return (f"{t}  [{ev.get('backend')}] {ev.get('agente')} · {ev.get('modelo')} · in {ev.get('input', 0):,} "
                f"(caché {ev.get('cached', 0):,}) · out {ev.get('output', 0):,} · {ev.get('seg', 0):.0f}s  {ev.get('resultado', '')[:100]}")
    if ev["tipo"] == "permiso":
        h = ev.get("hasta")
        v = "" if ev.get("accion") != "dar" else (" hasta " + dt.datetime.fromtimestamp(h).strftime("%m-%d %H:%M") if h else " (siempre)")
        return f"{t}  [permiso] {ev.get('por', '?')}: {ev.get('accion')} {ev.get('regla')} a {ev.get('rol')}{v}"
    return f"{t}  {ev['tipo']}"


def cmd_bitacora(a):
    desde = desde_ts(a.desde)
    sel = lambda: [e for e in eventos.leer(desde) if e["tipo"] in ("msg", "uso", "permiso")
                   and (not a.agente or a.agente in (e.get("de"), e.get("a"), e.get("agente"), e.get("agente", "").removesuffix("-codex")))]
    evs = sorted(sel(), key=lambda e: e["ts"])
    for e in evs: print(fmt(e, a.completo))
    if not evs and not a.seguir: print("(sin eventos en ese período; ¿corriste `central importar central`?)")
    if a.seguir:
        ult = evs[-1]["ts"] if evs else time.time()
        try:
            while True:
                time.sleep(1.5)
                for e in sorted(sel(), key=lambda e: e["ts"]):
                    if e["ts"] > ult: print(fmt(e, a.completo), flush=True); ult = e["ts"]
        except KeyboardInterrupt: pass


def cmd_optimizador(a):
    desde = desde_ts(a.desde)
    msgs = sorted(eventos.leer(desde, "msg"), key=lambda m: m["ts"])
    pedidos = [m for m in msgs if m["a"] == "optimizador" and buzon.prefijo(m["cuerpo"]) == "PEDIR-CONTEXTO"]
    listos = [m for m in msgs if m["de"] == "optimizador" and buzon.prefijo(m["cuerpo"]) == "CONTEXTO-LISTO"]
    antes = despues = n = 0
    lat = []
    for p in pedidos:
        s = next((l for l in listos if l["ts"] >= p["ts"]), None)
        if s: lat.append(s["ts"] - p["ts"])
    for l in listos:
        f = re.search(r"[Ff]uente\s*[≈~]\s*([\d.,]+k?)\s*tokens?\s*[→>-]+\s*~?([\d.,]+k?)", l["cuerpo"])
        if f and (x := buzon.tokens_declarados(f[1])) and (y := buzon.tokens_declarados(f[2])): antes += x; despues += y; n += 1
    print(f"Optimizador — desde {dt.datetime.fromtimestamp(desde):%Y-%m-%d}")
    print(f"  pedidos: {len(pedidos)}  entregas: {len(listos)}  latencia mediana: " + (f"{sorted(lat)[len(lat)//2]:.0f}s" if lat else "n/d"))
    if n: print(f"  compresión declarada ({n} entregas): ~{antes:,.0f} → ~{despues:,.0f} tokens (x{antes/max(despues,1):.0f}; ahorro ≈ {antes-despues:,.0f} por lectura)")
    else: print("  compresión declarada: ninguna entrega trae «Fuente ≈N tokens → ~M»")
    for l in listos:
        print(f"  {dt.datetime.fromtimestamp(l['ts']):%m-%d %H:%M} → {l['a']:<12} {' '.join(l['cuerpo'].split())[:110]}")


def cmd_uso(a):
    if a.reiniciar:
        uso.reiniciar()
        print("consumo reiniciado a cero")
        return
    r = uso.resumen(desde_ts(a.desde), a.por)
    print(f"{a.por:<18} {'tareas':>6} {'in':>11} {'caché':>11} {'out':>9} {'min':>6}")
    for k, t in sorted(r.items(), key=lambda x: -x[1]["input"]):
        print(f"{k:<18} {t['tareas']:>6} {t['input']:>11,} {t['cached']:>11,} {t['output']:>9,} {t['seg']/60:>6.1f}")


def cmd_permisos(a):
    if a.sub == "ver":
        for n in [a.rol] if a.rol else [r.nombre for r in config.listar_roles()]: print(permisos.describir(n))
        if not a.rol:
            cfg = permisos.principal()
            print("principal (lo definís vos en permisos.toml): comandos " + ", ".join(cfg["comandos"]) + (" · denegar " + ", ".join(cfg["denegar"]) if cfg["denegar"] else ""))
    elif a.sub == "dar":
        if a.rol not in permisos.PRINCIPAL: config.cargar_rol(a.rol)   # falla si el rol no existe
        c = permisos.dar(a.rol, a.regla, a.hasta)
        print(f"ok: {a.rol} + {c['regla']} (" + ("siempre" if c["hasta"] is None else "hasta " + dt.datetime.fromtimestamp(c["hasta"]).strftime("%m-%d %H:%M")) + ")")
    else:
        n = permisos.quitar(a.rol, a.regla)
        print(f"quitadas: {n}" + ("" if n else " (solo se quitan concesiones; el perfil base se edita en permisos.toml)"))


def config_backends():
    from .backends import BACKENDS
    return BACKENDS


def listar_modelos():
    for m in config.catalogo_modelos():
        print(f"{m['id']:<24} {m['backend']:<8} costo {m['costo']:<6} {m['para-que-sirve']}")


def _propuesta(id_):
    return next((e for e in eventos.leer(tipo="propuesta") if e.get("id") == id_), None)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="central"); sub = ap.add_subparsers(dest="cmd")
    m = sub.add_parser("msg").add_subparsers(dest="sub", required=True)
    e = m.add_parser("enviar"); e.add_argument("de"); e.add_argument("a"); e.add_argument("texto")
    l = m.add_parser("leer"); l.add_argument("agente", nargs="?"); l.add_argument("--desde", default="24h")
    b = sub.add_parser("bitacora"); b.add_argument("--desde", default="24h"); b.add_argument("--agente")
    b.add_argument("--completo", action="store_true"); b.add_argument("--seguir", action="store_true")
    o = sub.add_parser("optimizador"); o.add_argument("--desde", default="7d")
    u = sub.add_parser("uso"); u.add_argument("--desde", default="7d"); u.add_argument("--por", default="backend", choices=["backend", "agente", "modelo", "proyecto"]); u.add_argument("--reiniciar", action="store_true")
    i = sub.add_parser("importar"); i.add_argument("origen", choices=["central"])
    r = sub.add_parser("correr"); r.add_argument("rol"); r.add_argument("tarea"); r.add_argument("-C", default=".")
    r.add_argument("-p", "--proyecto"); r.add_argument("-t", "--id", help="ID de tarea del tablero: se toma antes y se marca lista/bloqueada después"); r.add_argument("--de", default=None, help="quién delega (por defecto, el agente que te lanzó)")
    r.add_argument("--backend", choices=list(config_backends())); r.add_argument("--modelo"); r.add_argument("--propuesta"); r.add_argument("--escribir", choices=["si", "no"])
    r.add_argument("--ligero", choices=["si", "no", "lectura"], help="claude sin herramientas (si), con todas (no) o solo Read para imágenes (lectura)")
    r.add_argument("--simular", action="store_true", help="solo imprime el prompt que recibiría el modelo (no llama a nadie)")
    sg = sub.add_parser("seguir", help="sigue un hilo de Codex ya empezado (reusa caché, más barato)"); sg.add_argument("hilo"); sg.add_argument("mensaje")
    pm = sub.add_parser("permisos").add_subparsers(dest="sub", required=True)
    pv = pm.add_parser("ver"); pv.add_argument("rol", nargs="?")
    pd = pm.add_parser("dar"); pd.add_argument("rol"); pd.add_argument("regla"); pd.add_argument("--hasta", default="1h", help="30m, 1h, 2d o siempre (def. 1h)")
    pq = pm.add_parser("quitar"); pq.add_argument("rol"); pq.add_argument("regla")
    dc = sub.add_parser("decisiones", help="registro de decisiones de lanzamiento (para entrenar el selector de modelo)").add_subparsers(dest="sub", required=True)
    dr = dc.add_parser("registrar"); dr.add_argument("--motor", required=True); dr.add_argument("--modelo", default=""); dr.add_argument("--origen", default="sub"); dr.add_argument("--dir", default=""); dr.add_argument("--nombre", default=""); dr.add_argument("--motivo", default=""); dr.add_argument("--prompt-file", required=True)
    dce = dc.add_parser("cerrar"); dce.add_argument("id"); dce.add_argument("estado", choices=["terminado", "error"]); dce.add_argument("--tokens", type=int, default=0); dce.add_argument("--seg", type=float, default=0.0)
    dv = dc.add_parser("veredicto"); dv.add_argument("id", help="id, o 'ultima'"); dv.add_argument("valor", choices=["bien", "mal"]); dv.add_argument("--nota", default="")
    dl = dc.add_parser("ver"); dl.add_argument("-n", type=int, default=20)
    dx = dc.add_parser("exportar"); dx.add_argument("--solo-con-veredicto", action="store_true")
    sub.add_parser("principal", help="abre Claude Code en esta carpeta como agente principal (flags extra van a claude)")
    sub.add_parser("roles")
    sub.add_parser("modelos")
    p = sub.add_parser("proponer"); p.add_argument("funcion"); p.add_argument("--modelo", required=True); p.add_argument("--motivo", required=True); p.add_argument("--tarea", required=True)
    apv = sub.add_parser("aprobar"); apv.add_argument("id"); apv.add_argument("--modelo")
    rej = sub.add_parser("rechazar"); rej.add_argument("id")
    vr = sub.add_parser("ver", help="abre el visor: grafo de comunicación, logs o uso por IA (requiere PyQt6)"); vr.add_argument("vista", nargs="?", default="grafo", choices=["grafo", "logs", "uso"])
    argv = sys.argv[1:] if argv is None else argv
    if not argv:                                  # sin argumentos: abre (o enfoca) la ventana del Claude principal
        os.execv(str(Path(__file__).resolve().parents[2] / "bin" / "central-abrir"), ["central-abrir"])
    if argv[0] == "principal":                    # `central principal [flags de claude]`: Claude Code aquí mismo como agente principal
        lanzar.lanzar(argv[1:]); return
    a = ap.parse_args(argv)
    if a.cmd == "msg" and a.sub == "enviar": buzon.enviar(a.de, a.a, a.texto); print("ok")
    elif a.cmd == "msg":
        for ev in buzon.leer(a.agente, desde_ts(a.desde)): print(fmt(ev, True))
    elif a.cmd == "bitacora": cmd_bitacora(a)
    elif a.cmd == "permisos": cmd_permisos(a)
    elif a.cmd == "optimizador": cmd_optimizador(a)
    elif a.cmd == "uso": cmd_uso(a)
    elif a.cmd == "importar": print("importado:", importar.desde_central())
    elif a.cmd == "decisiones":
        from . import decisiones as dec
        if a.sub == "registrar": print(dec.registrar(Path(a.prompt_file).read_text(), a.motor, a.modelo, a.origen, a.dir, a.nombre, a.motivo))
        elif a.sub == "cerrar": dec.resultado(a.id, a.estado, a.tokens, a.seg)
        elif a.sub == "veredicto":
            id_ = a.id if a.id != "ultima" else (dec.unidas() or [{"id": ""}])[-1]["id"]
            dec.veredicto(id_, 1 if a.valor == "bien" else -1, a.nota); print("ok", id_)
        elif a.sub == "ver":
            for f in dec.unidas()[-a.n:]:
                v = {1: "👍", -1: "👎", None: "-"}[f["veredicto"]]
                print(f"{f['id']}  {f['motor']:<7} {f['modelo'][:24]:<24} {f['estado']:<10} {v}  {f['prompt'].splitlines()[0][:70] if f['prompt'] else ''}")
        elif a.sub == "exportar": print(dec.exportar(a.solo_con_veredicto))
    elif a.cmd == "ver":
        try: from .gui.visor import main as visor_main
        except ImportError as e: sys.exit(f"[central] falta PyQt6 para el visor ({e}). Instalá: uv tool install --reinstall '.[ui]'")
        sys.exit(visor_main(a.vista))
    elif a.cmd == "seguir":
        d = decisiones.por_hilo(a.hilo)
        if not d: sys.exit(f"central: no encuentro el hilo {a.hilo} (solo se pueden seguir hilos de Codex lanzados con central)")
        res = ejecutor.correr(d["nombre"], a.mensaje + "\n\n(Terminá con el mismo formato de mensaje final: LISTO/BLOQUEADO/NECESITA, archivos, verificado.)",
                              Path(d["directorio"]), None, None, False, {"model": d["modelo"], "backend": d["motor"]}, None, a.hilo)
        tablero.soltar_bloqueos(f"{d['nombre']}-{d['motor']}")
        print(res.texto)
        print(f"\n[central] {d['nombre']} · {res.modelo} · in {res.entrada:,} (caché {res.cache:,}) · out {res.salida:,} · hilo {res.hilo or a.hilo}", file=sys.stderr)
        sys.exit(0 if res.codigo == 0 else 1)
    elif a.cmd == "roles":
        for rol in config.listar_roles(): print(f"{rol.nombre:<20} {rol.prompt.splitlines()[0] if rol.prompt else ''}")
    elif a.cmd == "modelos": listar_modelos()
    elif a.cmd == "proponer":
        if not config.modelo_por_id(a.modelo): sys.exit(f"modelo desconocido: {a.modelo}")
        config.cargar_rol(a.funcion)
        ident = uuid.uuid4().hex[:12]
        eventos.registrar("propuesta", id=ident, funcion=a.funcion, modelo=a.modelo, motivo=a.motivo, tarea=a.tarea)
        print(ident)
    elif a.cmd == "aprobar":
        p = _propuesta(a.id)
        if not p: sys.exit(f"propuesta inexistente: {a.id}")
        elegido = a.modelo or p["modelo"]
        if not config.modelo_por_id(elegido): sys.exit(f"modelo desconocido: {elegido}\nEjecutá `central modelos`.")
        eventos.registrar("aprobacion", id=a.id, modelo=elegido)
        print(f"aprobada {a.id} · {elegido}")
    elif a.cmd == "rechazar":
        if not _propuesta(a.id): sys.exit(f"propuesta inexistente: {a.id}")
        eventos.registrar("rechazo", id=a.id)
        print(f"rechazada {a.id}")
    elif a.cmd == "correr":
        if not a.modelo:
            sys.exit("central: --modelo es obligatorio. Modelos disponibles:\n" + "\n".join(f"  {m['id']} ({m['backend']}, costo {m['costo']}) — {m['para-que-sirve']}" for m in config.catalogo_modelos()))
        aj = {k: v for k, v in (("backend", a.backend), ("model", a.modelo), ("escribir", None if a.escribir is None else a.escribir == "si"), ("ligero", None if a.ligero is None else (a.ligero if a.ligero == "lectura" else a.ligero == "si"))) if v is not None}
        agente = f"{a.rol}-{a.backend or 'codex'}"
        if a.id and not a.simular:
            if err := tablero.tomar(a.id, agente, a.proyecto): sys.exit(f"BLOQUEADO: no pude tomar la tarea #{a.id}: {err}")
        res = ejecutor.correr(a.rol, a.tarea, Path(a.C), a.proyecto, a.de, a.simular, aj, a.propuesta)
        if not a.simular:
            tablero.soltar_bloqueos(agente)
            if a.id: tablero.cerrar(a.id, agente, a.proyecto, res.texto)
        print(res.texto)
        if not a.simular:
            print(f"\n[central] {a.rol} · {res.modelo} · in {res.entrada:,} (caché {res.cache:,}) · out {res.salida:,}", file=sys.stderr)
        sys.exit(0 if res.codigo == 0 else 1)


if __name__ == "__main__":
    main()
