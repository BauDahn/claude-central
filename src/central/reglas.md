## Reglas comunes (valen para cualquier agente, con cualquier modelo)
- Usá primero el CONTEXTO COMPARTIDO de abajo (si hay). No releas el repo entero ni documentos largos: ya están resumidos ahí.
- Si te falta contexto que no está, decilo en el mensaje final en tu respuesta; no explores a ciegas.
- Trabajá solo en lo pedido; tareas chicas y concretas. Verificá lo que hiciste (tests, ejecutar) cuando se pueda.
- Respondé libremente, sin formato obligatorio: mensajes cortos, rutas en vez de contenido.

## Delegación desde el agente principal
Las funciones (constructor, interfaz, diseno, orquestador, optimizador, contextualizador, revisor, investigador, general y otras) definen el trabajo y el perfil de permisos; nunca fijan modelo ni backend. Consultá `central modelos` para elegir un modelo disponible.

El agente principal NUNCA ejecuta `central correr` sin aprobación explícita del usuario. Primero registra la propuesta con `central proponer <funcion> --modelo <id> --motivo "…" --tarea "…"`, presenta la tarjeta y espera la decisión. Después de aprobar, ejecuta `central correr <funcion> "tarea" --modelo <id> --propuesta <id>`. Si se rechaza, no lanza esa tarea.

Formato obligatorio de la tarjeta: bloque cercado con lenguaje `propuesta` y un único objeto JSON con `id`, `funcion`, `modelo_recomendado`, `alternativas` (lista de ids o `{ "id": "…" }`), `motivo` y `tarea`. Ejemplo: ` ```propuesta\n{"id":"abc123","funcion":"revisor","modelo_recomendado":"claude-sonnet-5-5","alternativas":["gpt-6-luna"],"motivo":"…","tarea":"…"}\n``` `.
