# Arquitectura: agentes en paralelo, comunicación y ahorro de tokens

Esta es la idea de fondo: **una sola persona habla con un único Claude (`central`), y ese Claude reparte el trabajo entre varias sesiones de Claude Code que corren en paralelo**, cada una en su propia ventana y con su propio rol. Nada de esto es un framework: son sesiones normales de Claude Code, unos scripts de shell y archivos Markdown.

```
                         tú (voz)
                            │
                  ┌─────────▼─────────┐
                  │  central          │  habla contigo (TTS + dictado)
                  │  (~/central)      │  ve y coordina todas las sesiones
                  └───┬───────────┬───┘
        ListAgents /  │           │  \ SendMessage
        SendMessage   │           │   \
          ┌───────────▼──┐   ┌────▼──────────┐
          │ orquestador  │   │  optimizador  │   (residente, en segundo plano)
          │ reparte tareas│  │  cachea contexto│
          └──┬────┬────┬─┘   └───▲───────────┘
   ASIGNA    │    │    │         │ PEDIR-CONTEXTO / CONTEXTO-LISTO
      ┌──────▼┐ ┌─▼────┐ ┌▼─────┐│
      │frontend│ │backend│ │...  ├┘   cada agente lee primero contexto/INDEX.md
      └────────┘ └──────┘ └──────┘
                     │
        ~/agentes/contexto/  (docs/, mapas/, prompts/, INDEX.md)  ← memoria compartida en disco
```

## 1. Cómo corren en paralelo

- **Un agente = una ventana de kitty = una sesión de Claude Code.** `~/agentes/lanzar <nombre> [workspace]` abre `kitty --class agente-<nombre>` en el workspace que le indiques (sin robar el foco) y dentro ejecuta `bin/_run`, que hace `claude -n <nombre> "<prompt de rol + _comun.md>"`.
- **La definición vive en `agentes.conf`:** una línea `nombre|directorio|rol.md`. El directorio es donde arranca la sesión; el rol es el prompt inicial.
- **No duplica:** `lanzar` mira con `hyprctl clients` si ya hay una ventana con esa clase y, si existe, no abre otra. `listar` muestra estado y workspace; `cerrar` cierra la ventana.
- **El nombre es la identidad.** La clase de ventana `agente-<nombre>` sirve para encontrar al agente, para que el dictado por voz sepa a qué terminal enviar el texto ("beta, hacé X") y para que `central` use ese nombre en `SendMessage`.
- Los agentes no comparten memoria de conversación: cada uno tiene su propio contexto. Lo que comparten es **disco** (el repo en el que trabajan y la carpeta `contexto/`) y **mensajes**.

## 2. Cómo se comunican

Hay dos canales:

1. **Mensajes entre sesiones** con las herramientas de Claude Code `ListAgents` (ver quién existe) y `SendMessage` (`to=<nombre>`). Es la vía de control.
2. **Archivos en disco** (`~/agentes/contexto/`). Es la vía de datos: se pasan **rutas, no contenido**.

Regla de oro: **al usuario solo se llega a través de `central`**. Los subagentes no hablan por voz; si necesitan una decisión, le escriben a `central`, que se la plantea al usuario. Así el usuario tiene una sola conversación en vez de una por agente.

### Protocolo de mensajes
La primera línea de cada mensaje lleva un prefijo fijo, para que sea fácil de leer y de procesar:

| Mensaje | De → a | Significado |
|---|---|---|
| `ASIGNA: <agente> <tarea> \| contexto: <rutas>` | orquestador → agente | Te encargo esta tarea; el contexto relevante está en estas rutas. |
| `NECESITA: <agente> <qué>` | agente → orquestador | Me falta contexto o que otro agente haga algo. |
| `LISTO: <resumen> \| archivos: <rutas>` | agente → orquestador | Terminé; esto cambió. |
| `PEDIR-CONTEXTO: <qué> \| fuente: <ruta/url> \| para: <agente>` | agente → optimizador | Procesá esta fuente grande por mí. |
| `CONTEXTO-LISTO: <ruta> (~N tokens) — <resumen>` | optimizador → agente | Ya está listo y compacto en esta ruta. |

Los mensajes son cortos a propósito: cada token que viaja entre agentes se paga.

## 3. El orquestador

Rol: **descomponer una tarea grande en subtareas y decidir quién hace cada una.** No implementa (salvo cosas triviales).

- Recibe la tarea de `central`, la divide y reparte con `ASIGNA`, indicando qué rutas de `contexto/` necesita cada uno.
- Antes de asignar, le avisa al optimizador qué contexto va a hacer falta para que lo **precargue**.
- Atiende los `NECESITA` de los demás y contesta con la ruta o el `ASIGNA` que lo resuelve.
- Recibe los `LISTO`, **verifica que el conjunto funcione** y le resume el resultado a `central` en pocas líneas.
- **Evita conflictos:** dos agentes no deben editar los mismos archivos a la vez; si hay riesgo, serializa.
- Usa `ListAgents` para ver quién está abierto. Si falta un agente, **le pide a `central` que lo lance** (nunca lanza sesiones por su cuenta).

Los demás agentes son especialistas de solo lo suyo: `frontend`, `backend`, `seguridad` (auditoría defensiva), `ideas` (propone, no escribe código) y `revisor` (code review de solo lectura).

## 4. El optimizador (segundo plano)

Rol: **que el resto de agentes procese menos tokens y entienda mejor el material.** Corre todo el tiempo, "residente"; nadie le habla por voz, solo atiende `PEDIR-CONTEXTO`.

Bucle:
1. Lee la fuente y la convierte al formato compacto adecuado:
   - documento (PDF, Office, HTML) → `contexto/docs/<tema>.md` en Markdown;
   - repositorio → `contexto/mapas/<proyecto>.md` (árbol, módulos, funciones y clases clave, dependencias, cómo correrlo, trampas);
   - prompt largo → `contexto/prompts/<agente>.md` comprimido.
2. Escribe **de forma atómica** (archivo temporal + `mv`) y cada archivo empieza con un comentario con su **fuente y fecha/hash**, para saber si quedó viejo.
3. Actualiza `contexto/INDEX.md` (una línea por entrada: `ruta | fuente | fecha | ~tokens | resumen`), sin duplicar.
4. Responde `CONTEXTO-LISTO: <ruta> (~N tokens) — <resumen>`.
5. Si la fuente cambió desde la fecha de la entrada, **la refresca antes de responder**.
6. Mide siempre tokens aproximados **antes y después**.

Condición importante: **no instala herramientas sin aprobación del usuario** (la pide a `central`). Si no hay herramienta para algo, lo hace a mano y lo dice.

## 5. Cómo se ahorran tokens

Las reglas están en `agentes/roles/_comun.md` y las siguen todos los agentes:

1. **Mirar primero `contexto/INDEX.md`.** Si hay una entrada vigente para lo que necesitas, lees solo ese archivo compacto.
2. **No leer enteros PDFs, documentos largos ni repos.** Se le pide al optimizador (`PEDIR-CONTEXTO`) y se espera `CONTEXTO-LISTO`. Para archivos chicos o ediciones puntuales se lee directo.
3. **Pasar rutas, no contenido**, y mensajes cortos.
4. **Un solo escritor del caché:** solo el optimizador escribe en `contexto/`; los demás lo leen. Evita pisadas y duplicados.
5. **Un mapa del repo en lugar del repo:** un `mapas/<proyecto>.md` de ~1.000 tokens evita que cada agente recorra cientos de archivos.

### Proyectos de GitHub en los que se apoya (a evaluar)
El rol del optimizador los **recomienda como referencia** y le indica verificar licencia y estado actual antes de proponer ninguno. No vienen instalados ni integrados por defecto: el optimizador los evalúa y, si cree que valen la pena, pide permiso para instalarlos.

| Proyecto | Para qué |
|---|---|
| [microsoft/markitdown](https://github.com/microsoft/markitdown) | PDF/Office → Markdown. Rápido y simple. |
| [docling](https://github.com/docling-project/docling) (IBM) | PDF/Office → Markdown con mejor manejo de tablas y layouts. |
| [marker](https://github.com/datalab-to/marker) (datalab) | PDF → Markdown; mejor con matemática y con GPU. |
| [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) | Grafo de conocimiento de un repo con tree-sitter; consultable por agentes y como servidor MCP. |
| [microsoft/LLMLingua](https://github.com/microsoft/LLMLingua) | Compresión de prompts largos (LLMLingua-2, LongLLMLingua), hasta ~20x. |

Un caveat honesto: **no todo conversor ayuda**. En un experimento propio con un RAG, activar un parser más sofisticado (docling sin OCR) *empeoró* los resultados en algunos corpus, así que conviene **medir antes de adoptar** — por eso el optimizador mide antes/después.

## 6. Coordinación sin pisarse: tablero, bloqueos y aislamiento

**Tablero de tareas (`tareas`).** Estado compartido en `~/agentes/tareas/<proyecto>.json`, con bloqueo de archivo (`flock`), así que `tomar` es **atómico**: si 8 agentes intentan tomar la misma tarea a la vez, gana uno solo (hay un test). Estados: `pendiente → en_curso → hecha` (o `bloqueada`). Soporta dependencias (`--dep`) y asignación (`--para`). El orquestador crea las subtareas con `tareas add` y manda el ID en el `ASIGNA`; los agentes hacen `tomar` y `listo`. Como vive en disco, **sobrevive a reinicios**: si el orquestador se cae, otro puede leer el tablero y seguir. `tareas liberar` devuelve a pendiente la tarea de un agente que murió.

**Bloqueos de archivo (`bloqueo`).** Un hook `PreToolUse` sobre `Edit|Write|MultiEdit|NotebookEdit` ejecuta `bloqueo hook`: si el archivo (o su carpeta) lo tiene otro agente, **bloquea la edición** (exit 2) con un mensaje; si no, lo toma por 30 min y renueva en cada edición. No hace nada si no hay `$AGENTE`, así que `central` y tus sesiones normales no se ven afectadas. Es una red de seguridad: el problema se evita de raíz con lo siguiente.

**Aislamiento con `git worktree` (`worktree=1`).** En `agentes.conf`, `frontend|~/app|roles/frontend.md|model=sonnet,worktree=1` arranca esa sesión con `claude --worktree <nombre>`: cada agente edita **su propia copia y rama** del repo, sin posibilidad de pisar a otro. El orquestador integra los resultados (merge) cuando cada uno reporta `LISTO`.

## 7. Estado que sobrevive a un apagado

- `lanzar` anota cada agente abierto (y su workspace) en `~/agentes/estado/abiertos.json`; `cerrar` lo borra (cerrarlo a propósito significa "no restaurar"). Un apagado no pasa por `cerrar`, así que el registro queda.
- `~/agentes/restaurar` reabre los que estaban abiertos, en su workspace, y **retoma su conversación** (`claude --resume <nombre>`) si existe una sesión con ese nombre; si no, arranca limpia con su rol. `restaurar --ver` solo lista. Ponelo en Hyprland: `exec-once = ~/agentes/restaurar`.
- `~/agentes/guardar-estado` escribe `estado/ESTADO.md` (agentes abiertos, tareas pendientes, contexto cacheado viejo). Hay un timer de systemd (`config/systemd/`) que lo corre cada 10 min: `systemctl --user enable --now guardar-estado.timer`. **`central` lo lee al arrancar** (está en su `CLAUDE.md`).

## 8. Medir el consumo: `tokens`

Lee las transcripciones de `~/.claude/projects/*/*.jsonl` (solo lectura) y suma por **agente** (el nombre `-n` de la sesión), proyecto, modelo, día o sesión: tokens de entrada nuevos, **leídos de caché**, escritos a caché, salida, turnos y tamaño del contexto. Deduplica por id de mensaje porque el log repite el streaming.

```
tokens --desde 2026-11-01 --por agente
tokens --por dia
tokens --sesion <id|nombre>     # contexto turno a turno
```
No convierte a dinero (los precios cambian). Sirve para ver qué agente gasta de más y dónde conviene un modelo más barato.

## 9. Caché de contexto que no se queda viejo: `contexto-check`

Recorre `contexto/INDEX.md` y marca cada entrada `ok`, `VIEJA`, `FALTA` o `?` (URL, no verificable). Si el archivo cacheado trae `git HEAD:` y la fuente es un repo, compara con el HEAD actual; si no, compara la fecha de modificación de la fuente con la de la entrada. Con `--pedir` imprime los `PEDIR-CONTEXTO` listos para el optimizador, que lo corre al arrancar. `guardar-estado` lo incluye en `ESTADO.md`.

## 10. Modelo según el rol

El 4º campo de `agentes.conf` acepta `model=<opus|sonnet|haiku|nombre completo>`. Los roles críticos (orquestador, seguridad) en uno más fuerte; los livianos (ideas, optimizador, compactador) en uno barato. Los valores de `agentes.conf.example` son **sugerencias razonables, no medidas**: con `tokens --por agente` podés comprobar cuánto gasta cada rol y ajustar.

## 11. Compactar conversaciones largas: `compactar`

Un subagente **no puede reescribir el contexto en vivo de otra sesión**, así que la salida es un documento para una sesión **nueva**.

- `compactar <id|nombre>` → `contexto/conversaciones/<sesion>.md` con las peticiones del usuario, las últimas respuestas, los archivos tocados y los comandos recientes, más un reporte de tamaño (contexto vivo vs. documento). Es **extractivo y gratis**; con `--resumir` añade decisiones, estado y pendientes usando un modelo barato (gasta tokens).
- `compactar nueva <doc.md>` abre `claude` cargando solo ese documento.
- **Aviso automático:** un hook `Stop` corre `compactar aviso`; cuando el contexto de una sesión supera `COMPACT_UMBRAL` (def. 150.000 tokens) escribe en `estado/avisos.log` y manda una notificación de escritorio, una sola vez por sesión.

**Frente a `/compact` de Claude Code:** `/compact` es in situ y conserva el hilo, pero el resumen lo decide el modelo y no queda como archivo. Este documento es más corto, auditable y versionable, y permite cambiar de modelo o de sesión. **Qué no está medido:** la calidad del resumen frente a `/compact` (hay que probarlo con una conversación real y comparar con `tokens --sesion`).

## 12. Cómo montar el tuyo

1. Ajusta `~/agentes/agentes.conf` con los directorios de tus proyectos.
2. Lanza `central` y pídele, por ejemplo: *"abre el orquestador y el optimizador sobre mi proyecto X"*.
3. Dale una tarea grande al orquestador (vía `central`). Verás cómo reparte con `ASIGNA`, cómo el optimizador va llenando `contexto/` y cómo vuelve un único resumen a `central`.
4. Para sumar un rol nuevo: crea `~/agentes/roles/<rol>.md`, añade una línea al `agentes.conf` y menciónalo en la lista de agentes de `_comun.md`.
5. Prueba las herramientas sin Hyprland ni Claude: `tests/run.sh`.

### Límites conocidos
- Cada agente es una sesión de Claude Code con su propio consumo: más agentes abiertos = más uso. Abre solo los que hagan falta.
- El protocolo de mensajes es una **convención en prompt**, no algo que imponga el código; los modelos pueden desviarse, por eso las reglas son cortas y explícitas.
- `bloqueo` es por convención de directorio: no detecta que dos agentes estén en rutas distintas pero con cambios incompatibles; para eso está `worktree=1` + la integración del orquestador.
- `restaurar` retoma la conversación por **nombre de sesión**; si hubo varias sesiones con el mismo nombre (p. ej. varios `orquestador`), retoma una de ellas. La parte que abre ventanas se probó con `hyprctl` y `claude` simulados, no en una sesión Hyprland real.
- Requiere Hyprland (`hyprctl`) para lanzar/encontrar ventanas; en otro entorno habría que adaptar `agentes/bin/_lib.sh` y `lanzar`.
