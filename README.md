# Claude Central

Un **Claude coordinador por voz** para Linux + Hyprland. Hablás con un Claude principal ("central") que ve todas tus otras sesiones de Claude Code, las supervisa, les delega trabajo y te lo cuenta en voz alta.

> Hecho en español (rioplatense), pero la voz de salida es inglesa y todo es configurable.

## Qué incluye

| Pieza | Qué hace |
|---|---|
| `voice/voice.py` | TTS local con [Kokoro](https://github.com/thewh1teagle/kokoro-onnx). Un hook lee en voz alta solo lo que Claude pone dentro de `<voz>…</voz>`. Con *barge-in* (se calla si hablás) y *ducking* (baja la música mientras habla). |
| `voice/listen.py` | Escucha continua con [faster-whisper](https://github.com/SYSTRAN/faster-whisper): dictás y el texto se escribe (y opcionalmente se envía) en la terminal correcta. |
| `voice/names.py` | Nombres por voz para cada terminal ("central", "alfa", "beta"…): decís el nombre y el dictado va a esa sesión. |
| `agentes/` | Lanzador de subagentes (`lanzar`, `cerrar`, `listar`) en ventanas kitty, cada uno con un rol (`agentes/roles/*.md`): orquestador, frontend, backend, seguridad, ideas, revisor y optimizador. |
| `central/` | El `CLAUDE.md` del Claude coordinador y `hoy`, un script que muestra tu agenda de Google Calendar. |
| `bin/` | `central` (abre/enfoca el coordinador) y `escucha` (controla el dictado). |

> **Cómo funciona el trabajo en paralelo** (orquestador, optimizador en segundo plano, protocolo de mensajes y ahorro de tokens): [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Requisitos

Linux con **Hyprland**, `kitty`, `wtype`, `jq`, PipeWire/PulseAudio (`pactl`, `parec`, `paplay`), Python 3.10+, `git` y [Claude Code](https://claude.com/claude-code). GPU NVIDIA opcional (Whisper usa CUDA si la hay, si no CPU).

## Instalación

```bash
git clone https://github.com/BauDahn/claude-central
cd claude-central
./install.sh          # SKIP_MODELS=1 ./install.sh si ya tenés los modelos de Kokoro
```

El instalador copia todo a `~/.local/share/claude-voice`, `~/.local/bin` y `~/agentes`, crea un venv, descarga los modelos de Kokoro (~350 MB), añade la sección de voz a `~/.claude/CLAUDE.md` y registra los hooks en `~/.claude/settings.json` (con copia de seguridad previa). Es seguro re-ejecutarlo.

## Uso

```bash
central                  # abre el Claude coordinador (en ~/central)
escucha on               # activa el dictado continuo (off | auto on | names | status)
~/agentes/lanzar backend ~     # abre un subagente (ver agentes.conf)
~/agentes/listar
```

Configurá tus agentes en `~/agentes/agentes.conf` (hay un `.example`): una línea `nombre|directorio|rol.md`. Para añadir uno nuevo, creá su rol en `~/agentes/roles/`.

### Variables útiles
`CLAUDE_VOICE` (voz Kokoro), `CLAUDE_VOICE_SPEED`, `CLAUDE_VOICE_DUCK`, `CLAUDE_VOICE_BARGE`, `LISTEN_MODEL` (def. `small`), `LISTEN_LANG` (def. `es`), `LISTEN_PROMPT` (pista para Whisper; útil para acentos), `HOY_CALENDARIO`, `TZ_LOCAL`.

## Licencia
MIT. Los modelos de Kokoro y Whisper tienen sus propias licencias.
