# Herramientas de Central para el agente principal

- `central roles`: lista funciones prefabricadas, independientes del modelo.
- `central modelos`: catálogo con backend, id, uso recomendado y costo relativo.
- `central proponer <funcion> --modelo <id> --motivo "…" --tarea "…"`: registra una propuesta y devuelve su id.
- `central aprobar <id> [--modelo otro]` / `central rechazar <id>`: registra la decisión del usuario.
- `central correr <funcion> "tarea" --modelo <id> -C <dir> [--backend X] [--propuesta <id>]`: ejecuta la función. Siempre exige modelo; el backend se deduce del catálogo.
- `central bitacora`, `central uso`, `central optimizador` y `central msg`: consultan eventos, consumo, contexto y mensajes.

El principal nunca ejecuta `central correr` antes de aprobación. Presenta primero una tarjeta en bloque cercado `propuesta` con JSON `{ "id", "funcion", "modelo_recomendado", "alternativas", "motivo", "tarea" }`; espera la decisión y ejecuta solo después de aprobar.

Para programar se usa la función `constructor`; para revisar, `revisor`; para contexto, `contextualizador`. Los perfiles de permisos se asignan a funciones en `permisos.toml`.
