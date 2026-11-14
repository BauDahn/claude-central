
## Comunicación y contexto (común a todos los agentes)
Agentes: orquestador, frontend, backend, seguridad, ideas, revisor, optimizador (residente, nadie le habla por voz), dj, alpha (RAG), beta (investigación), gamma (finanzas). Hablan entre sí con SendMessage (to=<nombre>). Al usuario solo se llega a través de "central".

Contexto compartido en ~/agentes/contexto/: docs/<tema>.md (documentos en Markdown), mapas/<proyecto>.md (mapa del repo), prompts/<agente>.md (prompts comprimidos), INDEX.md (una línea por entrada: ruta | fuente | fecha | ~tokens | resumen).

Reglas para ahorrar tokens:
1. Antes de leer un archivo grande (PDF, doc largo, repo entero), mirá contexto/INDEX.md. Si hay entrada vigente, leé solo ese archivo.
2. Si no está, NO lo leas entero: pedíselo al optimizador con PEDIR-CONTEXTO y esperá CONTEXTO-LISTO. Para archivos chicos o ediciones puntuales, leé directo.
3. Mensajes cortos: mandá rutas, no contenido. Primera línea con el prefijo.

Convención de mensajes (primera línea):
- `PEDIR-CONTEXTO: <qué> | fuente: <ruta/url> | para: <agente>`  (agente → optimizador)
- `CONTEXTO-LISTO: <ruta> (~N tokens) — <resumen de 1 línea>`  (optimizador → agente)
- `NECESITA: <agente> <qué contexto o tarea>`  (agente → orquestador)
- `ASIGNA: <agente> <tarea> | contexto: <rutas>`  (orquestador → agente)
- `LISTO: <resumen corto> | archivos: <rutas>`  (agente → orquestador)
Todo lo que sea para el usuario va a central con SendMessage, corto (no hablás por voz).
Para agentes que no son el optimizador: no escribas en contexto/ salvo que sea tu propia salida pedida.

Nota para el dj: tu script de Spotify es `$HOME/agentes/spotify/venv/bin/python $HOME/agentes/spotify/spotify.py <comando>` (ver rol). No necesitás contexto/ para la música.

## Herramientas compartidas (en tu PATH; tu nombre llega en $AGENTE)
- **Tablero de tareas** `tareas`: antes de empezar una tarea asignada, `tareas tomar <ID> -p <proyecto>` (falla si otro ya la tiene o faltan dependencias); al terminar, `tareas listo <ID> -p <proyecto> --nota "<resumen>"`; si te bloqueás, `tareas bloquear <ID> --motivo "..."`. `tareas ls -p <proyecto>` muestra todo. El ID va en el `ASIGNA`.
- **Bloqueos de archivo** (`bloqueo`): un hook toma el archivo automáticamente la primera vez que lo editás y lo suelta a los 30 min. Si te dice `BLOQUEADO`, otro agente lo está editando: no insistas; avisá al orquestador con `NECESITA:` o trabajá en otra cosa.
- **Consumo** (`tokens`): `tokens --por agente` muestra cuánto gastó cada sesión. Si tu contexto pasa de ~150k tokens, avisá al orquestador: conviene `compactar` y seguir en una sesión nueva.
- **Codex** (`cx`): la implementación pesada se delega a Codex, que gasta créditos de OpenAI y no tus tokens. `cx <rol> -C <dir> [-p <proyecto> -t <ID>] "<tarea concreta>"` corre un trabajador Codex con el modelo barato del rol (`cx roles`) y te devuelve solo su resumen (LISTO/BLOQUEADO/NECESITA + archivos + verificado). Con `-t` toma y cierra la tarea del tablero. Para correcciones sobre lo mismo usá `cx seguir <hilo> "<qué cambiar>"` (reusa el contexto en caché). Usá `rapido` para lo trivial (boilerplate, renombres). Tareas chicas y autocontenidas: dale archivos, criterio de "hecho" y cómo verificarlo. Revisá el resultado leyendo solo los archivos que cambió. `cx log` muestra el uso (sirve de evidencia para el reto de Codex).
