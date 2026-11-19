"""Backends: lo único que cambia según el modelo/proveedor. Todos devuelven un Resultado con el mismo formato.

  codex   -> `codex exec` (agente completo: edita archivos, corre comandos). Usa el perfil ~/.codex/<rol>.config.toml si existe.
  claude  -> `claude -p` (Claude Code con tu login, sin clave de API; edita archivos si escribir=true; ligero=true usa conversación mínima).
  agy     -> `agy -p` (Antigravity, modelos Gemini; escribir=true edita, si no modo plan de solo lectura).
  openai  -> cualquier API compatible con OpenAI (/chat/completions) con clave por variable de entorno.
             v0.2: SOLO conversación (sin herramientas): sirve para análisis, revisión, planificación; no edita archivos.
  eco     -> no llama a ningún modelo; devuelve el prompt (para probar el ejecutor sin gastar nada).
"""
import json, os, re, shutil, subprocess, tempfile, tomllib, urllib.error, urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import permisos
from .config import Rol


@dataclass
class Resultado:
    texto: str
    entrada: int = 0
    cache: int = 0
    salida: int = 0
    hilo: str | None = None
    codigo: int = 0
    modelo: str = "?"


def eco(rol: Rol, prompt: str, cwd: Path, sesion: dict | None = None) -> Resultado:
    return Resultado("LISTO: eco (no se llamó a ningún modelo) | archivos: - | verificado: -\n\n" + prompt, modelo="eco")


def openai(rol: Rol, prompt: str, cwd: Path, sesion: dict | None = None) -> Resultado:
    """`sesion` (dict mutable) guarda el historial entre turnos del chat."""
    o = rol.opciones
    env = o.get("api_key_env", "OPENAI_API_KEY")
    clave = os.environ.get(env)
    if not clave:
        return Resultado(f"BLOQUEADO: falta la variable de entorno {env} con la clave de la API.", codigo=2, modelo=o.get("model", "?"))
    url = o.get("base_url", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    mensajes = (sesion.setdefault("mensajes", []) if sesion is not None else []) + [{"role": "user", "content": prompt}]
    body = json.dumps({"model": o["model"], "messages": mensajes}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json", "Authorization": f"Bearer {clave}"})
    try:
        with urllib.request.urlopen(req, timeout=int(o.get("timeout", 300))) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        return Resultado(f"BLOQUEADO: la API respondió {e.code}: {e.read().decode(errors='ignore')[:300]}", codigo=1, modelo=o["model"])
    except (urllib.error.URLError, TimeoutError) as e:
        return Resultado(f"BLOQUEADO: no pude llamar a la API: {e}", codigo=1, modelo=o["model"])
    u = d.get("usage", {})
    det = u.get("prompt_tokens_details") or {}
    texto = d["choices"][0]["message"]["content"].strip()
    if sesion is not None:
        sesion["mensajes"] = mensajes + [{"role": "assistant", "content": texto}]
    return Resultado(texto, u.get("prompt_tokens", 0), det.get("cached_tokens", 0), u.get("completion_tokens", 0), modelo=o["model"])


def modelo_efectivo(rol: Rol) -> str:
    """Modelo que realmente usará el rol: el del rol, o (Codex) el del perfil ~/.codex/<perfil>.config.toml / config.toml."""
    if rol.opciones.get("model"):
        return rol.opciones["model"]
    if rol.backend == "codex":
        d = Path.home() / ".codex"
        for f in (d / f"{rol.opciones.get('perfil', rol.nombre)}.config.toml", d / "config.toml"):
            try:
                if f.exists() and (m := tomllib.loads(f.read_text()).get("model")):
                    return f"{m} (perfil {f.name.split('.')[0]})"
            except (OSError, ValueError):
                pass
        return "(el predeterminado de Codex)"
    return "?"


def modelo_corto(rol: Rol) -> str:
    """Nombre corto para el prompt: gpt-6-luna -> luna, claude-sonnet-5-5 -> sonnet, sin modelo definido -> default."""
    m = modelo_efectivo(rol).split(" (")[0]
    if m.startswith("(") or m == "?":
        return "default"
    m = re.sub(r"^(gpt-[\d.]+-|claude-)", "", m)
    return re.sub(r"(-\d+)+$", "", m) or m


def describir(ev: dict) -> str | None:
    """Traduce un evento JSON de `codex exec` a una línea legible (mejor esfuerzo: si el formato cambia, no muestra nada)."""
    t, item = ev.get("type", ""), ev.get("item") or {}
    it = item.get("type")
    if t == "turn.started": return "pensando…"
    if t == "item.started" and it == "command_execution": return "ejecutando: " + str(item.get("command", ""))[:110]
    if t == "item.completed" and it == "command_execution" and item.get("exit_code") not in (0, None): return f"  ↳ terminó con código {item.get('exit_code')}"
    if t == "item.completed" and it == "file_change":
        return "editó: " + ", ".join(str(c.get("path", "?")) for c in item.get("changes", [])[:5])
    if t == "item.started" and it in ("web_search", "mcp_tool_call"): return f"usando {it}: {item.get('query') or item.get('tool') or ''}"[:110]
    return None


def exe_codex() -> str | None:
    return shutil.which("codex") or next(iter(sorted((Path.home() / ".nvm/versions/node").glob("*/bin/codex"), reverse=True)), None)


def codex(rol: Rol, prompt: str, cwd: Path, sesion: dict | None = None) -> Resultado:
    """Con `sesion`, el primer turno abre un hilo de Codex y los siguientes lo retoman (`codex exec resume`)."""
    exe = exe_codex()
    if not exe:
        return Resultado("BLOQUEADO: no encuentro el binario de codex.", codigo=2)
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as t:
        out = Path(t.name)
    cmd = [exe, "exec", "--json", "--skip-git-repo-check", "-C", str(cwd), "-o", str(out)]
    if rol.opciones.get("perfil", rol.nombre) and (Path.home() / ".codex" / f"{rol.opciones.get('perfil', rol.nombre)}.config.toml").exists():
        cmd += ["-p", rol.opciones.get("perfil", rol.nombre)]
    if rol.opciones.get("model"): cmd += ["-m", rol.opciones["model"]]
    cmd += ["-s", "workspace-write" if permisos.perfil_rol(rol).edita else "read-only"]   # Codex no filtra comandos/rutas: eso va como instrucción en el prompt
    hilo = sesion.get("hilo") if sesion is not None else None
    final = ["resume", hilo, prompt] if hilo else [prompt]
    p = subprocess.Popen(cmd + final, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    r = Resultado("", modelo=modelo_efectivo(rol)); err = []
    progreso = sesion.get("progreso") if sesion is not None else None
    for line in p.stdout:
        try: ev = json.loads(line)
        except ValueError: continue
        t = ev.get("type")
        if progreso and (d := describir(ev)): progreso(d)
        if t == "thread.started": r.hilo = ev.get("thread_id")
        elif t == "turn.completed":
            u = ev.get("usage", {})
            r.entrada += u.get("input_tokens", 0); r.cache += u.get("cached_input_tokens", 0)
            r.salida += u.get("output_tokens", 0) + u.get("reasoning_output_tokens", 0)
        elif t in ("error", "turn.failed"): err.append(json.dumps(ev, ensure_ascii=False)[:400])
    r.codigo = p.wait()
    if sesion is not None and r.hilo:
        sesion["hilo"] = r.hilo
    r.texto = out.read_text().strip() if out.exists() else ""
    out.unlink(missing_ok=True)
    if not r.texto:
        r.texto = "BLOQUEADO: codex no devolvió mensaje final.\n" + "\n".join(err or [p.stderr.read().strip()[-600:]])
    return r


def _cmd_claude(rol: Rol, prompt: str, exe: str) -> list[str]:
    """Construye el comando Claude; `ligero=true` conversa sin herramientas para reducir tokens."""
    if rol.opciones.get("ligero"):
        lectura = rol.opciones["ligero"] == "lectura"   # solo la herramienta Read, para mirar imágenes adjuntas
        dirs = sorted({str(Path(m).parent) for m in re.findall(r"Imagen adjunta: (\S+)", prompt)}) if lectura else []
        cmd = [exe, "-p", "--output-format", "json", "--tools", "Read" if lectura else "", "--strict-mcp-config",
               "--setting-sources", "", "--no-session-persistence", "--system-prompt",
               rol.prompt or "Sos un asistente general, claro y breve."]
        if lectura: cmd += ["--allowedTools", "Read"] + [x for d in dirs for x in ("--add-dir", d)]
        if rol.opciones.get("model"): cmd += ["--model", rol.opciones["model"]]
        return cmd + ["--", prompt]
    r = permisos.reglas_claude(permisos.perfil_rol(rol))
    cmd = [exe, "-p", "--output-format", "json", "--allowedTools", ",".join(["Bash(central:*)", *r["allowed"]])]
    if rol.opciones.get("model"): cmd += ["--model", rol.opciones["model"]]
    if r["modo"]: cmd += ["--permission-mode", r["modo"]]
    if r["disallowed"]: cmd += ["--disallowedTools", ",".join(r["disallowed"])]
    return cmd + ["--", prompt]


def claude(rol: Rol, prompt: str, cwd: Path, sesion: dict | None = None) -> Resultado:
    """Claude Code en modo no interactivo (`claude -p`) como subagente: usa tu login, sin clave de API.
    Con `escribir` puede editar archivos (acceptEdits); sin él, solo lee y analiza."""
    exe = shutil.which("claude")
    if not exe:
        return Resultado("BLOQUEADO: no encuentro el binario de claude (Claude Code).", codigo=2)
    cmd = _cmd_claude(rol, prompt, exe)
    p = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=rol.opciones.get("timeout", 900))
    try: d = json.loads(p.stdout)
    except ValueError:
        return Resultado("BLOQUEADO: claude no devolvió JSON.\n" + (p.stderr or p.stdout).strip()[-600:], codigo=p.returncode or 1)
    u = d.get("usage", {})
    texto = re.sub(r"<voz>.*?</voz>\s*", "", d.get("result", ""), flags=re.S).strip()   # la etiqueta de voz es de otra herramienta
    if d.get("is_error"): texto = "BLOQUEADO: " + (texto or d.get("subtype", "error de claude"))
    return Resultado(texto, u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0),
                     u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0), d.get("session_id"),
                     1 if d.get("is_error") else 0, next(iter(d.get("modelUsage", {})), modelo_efectivo(rol)))


def agy(rol: Rol, prompt: str, cwd: Path, sesion: dict | None = None) -> Resultado:
    """Antigravity CLI (`agy -p`, modelos Gemini). `escribir=true` -> accept-edits; si no, modo plan (solo lectura)."""
    exe = shutil.which("agy")
    if not exe:
        return Resultado("BLOQUEADO: no encuentro el binario agy (Antigravity).", codigo=2)
    o = rol.opciones
    cuerpo = (rol.prompt + "\n\n" if rol.prompt else "") + prompt
    cmd = [exe, "-p", cuerpo, "--output-format", "json", "--mode", "accept-edits" if permisos.perfil_rol(rol).edita else "plan"]   # agy no filtra rutas/comandos: van en el prompt
    if o.get("model"): cmd += ["--model", o["model"]]
    if o.get("effort"): cmd += ["--effort", o["effort"]]
    try:
        p = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=o.get("timeout", 900))
    except subprocess.TimeoutExpired:
        return Resultado("BLOQUEADO: agy superó el tiempo límite.", codigo=1, modelo=o.get("model", "?"))
    try: d = json.loads(p.stdout)
    except ValueError:
        crudo = (p.stdout or "").strip() or (p.stderr or "").strip()
        if p.returncode == 0 and crudo:   # salida de texto plano: se devuelve completa
            return Resultado(crudo, codigo=0, modelo=o.get("model") or "agy")
        return Resultado("BLOQUEADO: agy no devolvió JSON (salida cruda abajo).\n" + crudo, codigo=p.returncode or 1, modelo=o.get("model") or "agy")
    u = d.get("usage", {}); texto = d.get("response") or d.get("text") or d.get("output") or ""
    if not isinstance(texto, str): texto = json.dumps(texto, ensure_ascii=False)
    texto = texto.strip()
    ok = d.get("status") == "SUCCESS"
    if not ok: texto = "BLOQUEADO: " + (texto or json.dumps(d, ensure_ascii=False)[:2000])
    return Resultado(texto, u.get("input_tokens", 0), u.get("cache_read_tokens", 0), u.get("output_tokens", 0) + u.get("thinking_tokens", 0),
                     d.get("conversation_id"), 0 if ok else 1, o.get("model") or "agy")


BACKENDS = {"codex": codex, "claude": claude, "agy": agy, "openai": openai, "eco": eco}
