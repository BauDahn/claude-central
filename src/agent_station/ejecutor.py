"""Ejecutor: aplica las reglas por fuera del modelo, para que valgan con cualquier backend.

  1. arma el prompt: rol + reglas comunes + CONTEXTO COMPARTIDO del directorio (del INDEX) + tarea
  2. si no hay contexto para ese directorio, deja un PEDIR-CONTEXTO en el buzón (para que lo atienda el optimizador)
  3. llama al backend del rol
  4. devuelve la respuesta del subagente tal cual (sin exigir formato)
  5. registra mensajes (buzón) y consumo (uso) en el registro común
"""
import dataclasses, os, time
from pathlib import Path

from . import buzon, contexto, decisiones, eventos, permisos, uso
from .backends import BACKENDS, Resultado
from .config import Rol, cargar_rol, modelo_por_id

REGLAS = (Path(__file__).parent / "reglas.md").read_text()


def armar_prompt(rol: Rol, tarea: str, cwd: Path, proyecto: str | None) -> tuple[str, list[contexto.Entrada]]:
    ctx = contexto.para_directorio(cwd)
    partes = [rol.prompt.strip(), REGLAS.strip()]
    if (pf := rol.opciones.get("_perfil")): partes.append("## PERMISOS\n" + pf.instrucciones())
    if proyecto: partes.append(f"Proyecto: {proyecto}")
    partes.append("## CONTEXTO COMPARTIDO\n" + (contexto.texto(ctx) if ctx else "(no hay contexto cacheado para este directorio)"))
    partes.append(f"## TAREA\nDirectorio de trabajo: {cwd}\n\n{tarea}")
    return "\n\n".join(p for p in partes if p), ctx


def prof_max() -> int:
    return int(os.environ.get("AGENT_STATION_MAX_PROF", "2"))


def correr(nombre: str, tarea: str, cwd: Path, proyecto: str | None = None, de: str | None = None, simular: bool = False,
           ajustes: dict | None = None, propuesta: str | None = None) -> Resultado:
    """ajustes: cambios puntuales al rol solo para esta tarea (backend, model, escribir...), decididos por quien delega."""
    de = de or os.environ.get("AGENT_STATION_AGENTE", "central")
    prof = int(os.environ.get("AGENT_STATION_PROFUNDIDAD", "0"))
    if prof >= prof_max():
        return Resultado(f"BLOQUEADO: profundidad máxima de delegación ({prof_max()}). Un subagente no puede lanzar otros más abajo: "
                         "avisale a quien te lo pidió para que decida él.", codigo=1)
    rol = cargar_rol(nombre)
    if ajustes: rol = dataclasses.replace(rol, opciones={**rol.opciones, **ajustes})
    model_id = (ajustes or {}).get("model")
    model = modelo_por_id(model_id) if model_id else None
    if not model and not simular:
        raise SystemExit("station: el modelo es obligatorio y debe estar en el catálogo; ejecutá `station modelos`.")
    if model:
        opts = {**rol.opciones, **{k: model[k] for k in ("base_url", "api_key_env") if k in model}}
        opts["backend"] = (ajustes or {}).get("backend") or model["backend"]
        opts["model"] = model["id"]
        rol = dataclasses.replace(rol, opciones=opts)
    # El perfil de permisos manda: `escribir` (del rol o de la tarea) solo puede bajarlo a lectura, nunca subirlo.
    esc = rol.opciones.get("escribir")
    rol = dataclasses.replace(rol, opciones={**rol.opciones, "_perfil": permisos.perfil_de(nombre, False if esc is False else None)})
    cwd = cwd.expanduser().resolve()
    if not cwd.is_dir():
        raise SystemExit(f"station: la carpeta de trabajo no existe: {cwd}\n  Creala primero (mkdir -p {cwd}) o indicá otra con -C.")
    agente = f"{nombre}"
    if propuesta:
        aprobacion = next((e for e in eventos.leer(tipo="aprobacion") if e.get("id") == propuesta), None)
        if not aprobacion:
            raise SystemExit(f"station: la propuesta {propuesta} todavía no fue aprobada.")
        elegido = aprobacion.get("modelo")
        if elegido and elegido != model_id:
            model = modelo_por_id(elegido)
            if not model: raise SystemExit(f"station: modelo aprobado desconocido: {elegido}")
            rol = dataclasses.replace(rol, opciones={**rol.opciones, **model, "model": elegido})
    eventos.registrar("lanzamiento", funcion=nombre, modelo=rol.opciones.get("model", ""), propuesta=propuesta, estado="corriendo")
    prompt, ctx = armar_prompt(rol, tarea, cwd, proyecto)
    if simular:
        return Resultado(prompt, modelo="(simulado)")
    if rol.backend not in BACKENDS:
        raise SystemExit(f"station: backend desconocido '{rol.backend}' en el rol {nombre} (hay: {', '.join(BACKENDS)})")
    buzon.enviar(de, agente, "ASIGNA: " + tarea, proyecto=proyecto, contexto=[str(e.ruta) for e in ctx])
    if not ctx:
        buzon.enviar(agente, "optimizador", f"PEDIR-CONTEXTO: mapa del directorio de trabajo | fuente: {cwd} | para: {agente}", proyecto=proyecto)
    dec_id = decisiones.registrar(tarea, rol.backend, rol.opciones.get("model", ""), "ejecutor", str(cwd), nombre)
    t0 = time.time()
    antes = {k: os.environ.get(k) for k in ("AGENT_STATION_PROFUNDIDAD", "AGENT_STATION_AGENTE")}
    os.environ["AGENT_STATION_PROFUNDIDAD"], os.environ["AGENT_STATION_AGENTE"] = str(prof + 1), agente   # lo heredan los subprocesos del backend
    try:
        r = BACKENDS[rol.backend](rol, prompt, cwd)
    except Exception as e:   # un fallo del backend no debe dejar la tarea sin registrar
        r = Resultado(f"BLOQUEADO: falló el backend '{rol.backend}': {type(e).__name__}: {e}", codigo=1)
    finally:
        for k, v in antes.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    dur = time.time() - t0
    primera = r.texto.splitlines()[0] if r.texto else ""
    buzon.enviar(agente, de, primera[:300], proyecto=proyecto)
    uso.registrar(agente, rol.backend, r.modelo, r.entrada, r.cache, r.salida, dur, tarea, primera, proyecto,
                  hilo=r.hilo, contexto_inyectado=len(ctx))
    decisiones.resultado(dec_id, "terminado" if r.codigo == 0 else "error", r.entrada + r.salida, dur)
    eventos.registrar("terminado", funcion=nombre, modelo=rol.opciones.get("model", ""), propuesta=propuesta,
                      estado="terminado" if r.codigo == 0 else "error")
    return r
