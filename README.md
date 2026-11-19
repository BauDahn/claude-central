# Claude Central

Un **Claude coordinador por voz** para Linux + Hyprland. Hablás con un Claude principal ("central") que ve todas tus otras sesiones de Claude Code, las supervisa, les delega trabajo y te lo cuenta en voz alta.

> Hecho en español (rioplatense), pero la voz de salida es inglesa y todo es configurable.

## Qué incluye

| Pieza | Qué hace |
|---|---|
| `voice/voice.py` | TTS local con [Kokoro](https://github.com/thewh1teagle/kokoro-onnx). Un hook lee en voz alta solo lo que Claude pone dentro de `<voz>…</voz>`. Con *barge-in* (se calla si hablás) y *ducking* (baja la música mientras habla). |
| `voice/listen.py` | Escucha continua con [faster-whisper](https://github.com/SYSTRAN/faster-whisper): dictás y el texto se escribe (y opcionalmente se envía) en la terminal correcta. |
| `voice/names.py` | Nombres por voz para cada terminal ("central", "alfa", "beta"…): decís el nombre y el dictado va a esa sesión. |
| `agentes/` | Lanzador de subagentes (`lanzar`, `cerrar`, `listar`) en ventanas kitty, cada uno con un rol (`agentes/roles/*.md`): orquestador, frontend, backend, seguridad, ideas, revisor, optimizador y compactador; con modelo por rol y, si querés, un `git worktree` por agente. |
| `agentes/bin/` | Herramientas compartidas: `tareas` (tablero atómico), `bloqueo` (hook anti-pisadas), `tokens` (consumo por agente), `contexto-check` (caché viejo), `compactar` (conversaciones largas → documento), `bitacora` (alias de `central bitacora`). Además `restaurar` y `guardar-estado` para sobrevivir a un apagado. |
| `agentes/bin/sub`, `sublog`, `reportar` | Lanzan **subagentes de cualquier IA** (agy, Claude, Codex) en una terminal visible, con un **log compartido en vivo** que lee el coordinador. |
| `src/central/` | El comando **`central`** (paquete Python): registro único de eventos, ejecutor multi-IA, permisos por rol, registro de decisiones y el visor del grafo/logs/uso. Tests en `tests/central/`. |
| `central/` | El `CLAUDE.md` del Claude coordinador y `hoy`, un script que muestra tu agenda de Google Calendar. |
| `bin/` | `central-abrir` (abre/enfoca la ventana del coordinador; lo llama `central` sin argumentos) y `escucha` (controla el dictado). |

> **Cómo funciona el trabajo en paralelo** (orquestador, optimizador en segundo plano, protocolo de mensajes y ahorro de tokens): [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Requisitos

Linux con **Hyprland**, `kitty`, `wtype`, `jq`, PipeWire/PulseAudio (`pactl`, `parec`, `paplay`), Python 3.11+, [uv](https://docs.astral.sh/uv/), `git` y [Claude Code](https://claude.com/claude-code). Opcionales: [Codex](https://developers.openai.com/codex) y agy (Antigravity) como motores extra. GPU NVIDIA opcional (Whisper usa CUDA si la hay, si no CPU).

## Instalación

```bash
git clone https://github.com/BauDahn/claude-central
cd claude-central
./install.sh          # SKIP_MODELS=1 ./install.sh si ya tenés los modelos de Kokoro
```

El instalador copia la voz a `~/.local/share/claude-voice` y los agentes a `~/agentes`, instala el comando `central` con `uv tool install --editable` (con el visor Qt), crea un venv, descarga los modelos de Kokoro (~350 MB), añade la sección de voz a `~/.claude/CLAUDE.md` y registra los hooks en `~/.claude/settings.json` (con copia de seguridad previa). Es seguro re-ejecutarlo.

## Uso

### Lo de todos los días
```bash
central                          # abre (o enfoca) la ventana del Claude coordinador
central principal                # Claude Code en esta carpeta como agente principal, con reglas y contexto de central
escucha on                       # dictado continuo (off | auto on | names | status)
```

### Ver el grafo, los logs y el uso por IA
```bash
central ver grafo                # visor: mapa de quién habla con quién, en vivo
central ver logs                 # el mismo visor, en lista cronológica de mensajes
central ver uso                  # consumo por IA / agente / modelo
central bitacora --desde 2d      # los mismos mensajes en texto (--agente X, --completo, --seguir)
central uso --por modelo         # consumo: backend | agente | modelo | proyecto
central optimizador              # qué logró el optimizador (pedidos, tokens ahorrados)
tokens --por agente              # detalle de Claude desde sus transcripciones (contexto por turno)
sublog                           # log compartido de los subagentes (--seguir en vivo, --crudo <nombre>)
```

### Lanzar subagentes de cualquier IA
El usuario elige o aprueba el motor y el modelo **antes** de lanzar: `sub` y `central correr` se niegan sin `--aprobado`.

```bash
sub --opciones                                   # motores y modelos disponibles
# terminal visible, interactiva, con permisos que aprobás vos:
sub agy "Gemini 4 Hydrogen (High)" ~/proyecto "tarea" --aprobado --motivo "por qué"
sub claude opus  ~/proyecto @tarea.txt --nombre revisor --aprobado --motivo "..."
sub codex gpt-6-luna ~/proyecto "tarea" --aprobado --motivo "..."
sub --lista                                      # subagentes lanzados y si siguen abiertos

# sin pantalla, devuelve solo el resumen (LISTO / BLOQUEADO / NECESITA):
central correr backend --backend codex --modelo gpt-6-luna -C ~/proyecto -p proyecto -t 3 "tarea" --aprobado --motivo "..."
central seguir <hilo> "corregí X"                # sigue un hilo de Codex (reusa caché)
central roles | central modelos                  # roles y catálogo de modelos con su costo
central proponer | aprobar | rechazar              # propuestas de lanzamiento con aprobación; central permisos ver|dar|quitar
```
Desde un subagente: `reportar "mensaje"` escribe en el log compartido que lee el coordinador.

### Registro de decisiones (para entrenar un selector de modelo)
Cada lanzamiento (`sub` o `central correr`) guarda prompt, motor, modelo, motivo, resultado y tokens. Vos le ponés el veredicto:
```bash
central decisiones ver                           # últimas decisiones
central decisiones veredicto ultima bien|mal     # tu 👍 / 👎
central decisiones exportar                      # JSONL listo para entrenar
```

### Agentes fijos y utilidades
```bash
~/agentes/lanzar backend ~       # abre un agente definido en agentes.conf
~/agentes/listar
~/agentes/restaurar              # reabre los agentes que estaban abiertos antes de apagar
tareas ls -p miproyecto          # tablero de tareas compartido
compactar <sesion>               # conversación larga -> documento corto para una sesión nueva
```

Configurá tus agentes en `~/agentes/agentes.conf` (hay un `.example`): una línea `nombre|directorio|rol.md|opciones`, con opciones `model=`, `worktree=1` y `motor=codex|agy`. Para añadir uno nuevo, creá su rol en `~/agentes/roles/`.

### Variables útiles
`CENTRAL_HOME` (datos de central, def. `~/.central`), `CENTRAL_ROLES`, `CENTRAL_CONTEXTO`, `AGENTES_HOME` (def. `~/agentes`), `CLAUDE_VOICE` (voz Kokoro), `CLAUDE_VOICE_SPEED`, `CLAUDE_VOICE_DUCK`, `CLAUDE_VOICE_BARGE`, `LISTEN_MODEL` (def. `small`), `LISTEN_LANG` (def. `es`), `LISTEN_PROMPT` (pista para Whisper; útil para acentos), `HOY_CALENDARIO`, `TZ_LOCAL`.

## Ejecutor multi-IA (`central correr`): Codex, Claude y agy

Claude planifica y revisa; el código lo escribe otra IA (Codex, Claude o agy) con el modelo adecuado a cada rol (`--backend codex|claude|agy`, `--modelo <id>` del catálogo `central modelos`). Para una terminal visible y aprobable usá `sub`.

```bash
central roles                                   # roles disponibles; central modelos: modelos y su costo
central correr backend --modelo gpt-6-luna -C ~/proyecto -p proyecto -t 3 "tarea concreta, criterio de hecho y cómo verificar"
central seguir <hilo> "corregí X"               # mismo hilo, reusa la caché
central uso                                     # uso por rol (tokens, tiempo, resultados)
```

`central correr` devuelve solo un resumen (`LISTO`/`BLOQUEADO`/`NECESITA` + archivos + verificado), toma y cierra la tarea del tablero, y suelta los bloqueos al terminar. Requiere `npm i -g @openai/codex && codex login`; el instalador copia los perfiles (orquestador/seguridad/ideas → esfuerzo alto, backend/frontend/revisor → medio, optimizador/rapido → modelo chico). Con `motor=codex` en `agentes.conf`, `lanzar` abre una sesión interactiva de Codex en vez de Claude.

## Equipo multi-máquina (`equipo`)

Varias personas, cada una con su máquina y su `central`, coordinadas por **un central orquestador**. Lo compartido vive en un repo de GitHub (lo único que ven todas las máquinas):

```bash
# en cada máquina, una vez (gh autenticado con acceso al repo):
equipo init --maquina ana --rol orquestador --repo org/proyecto --dir ~/proyectos/proyecto
equipo init --maquina beto --rol miembro    --repo org/proyecto --dir ~/proyectos/proyecto

equipo ver                       # (orquestador) estado de cada máquina, issues por máquina, PRs abiertos
equipo asignar beto "título" --cuerpo "qué, criterio de hecho"   # un issue = una rama = un PR
equipo mias                      # issues asignados a esta máquina
equipo avisar ana "PR #12 listo" # mensajes entre máquinas
equipo mensajes                  # mensajes nuevos para esta máquina
```

Cada máquina publica su estado (rama, cambios sin subir, agentes abiertos, últimas tareas de Codex) en un issue fijo del repo, cada 10 minutos con el timer de `guardar-estado`. El `CLAUDE.md` de central explica al Claude qué hacer según su rol.

## Desarrollo
```bash
uv tool install --editable '.[ui]'     # instala el comando central desde el repo
QT_QPA_PLATFORM=offscreen uv run --with pytest --with PyQt6 python -m pytest tests/central -q
bash tests/run.sh                      # pruebas de los scripts bash
```

## Licencia
MIT. Los modelos de Kokoro y Whisper tienen sus propias licencias.
