# Herramientas de Station para el agente principal

- `station roles`: lista funciones prefabricadas, independientes del modelo.
- `station modelos`: catálogo con backend, id, uso recomendado y costo relativo.
- `station proponer <funcion> --modelo <id> --motivo "…" --tarea "…"`: registra una propuesta y devuelve su id.
- `station aprobar <id> [--modelo otro]` / `station rechazar <id>`: registra la decisión del usuario.
- `station correr <funcion> "tarea" --modelo <id> -C <dir> [--backend X] [--propuesta <id>]`: ejecuta la función. Siempre exige modelo; el backend se deduce del catálogo.
- `station bitacora`, `station uso`, `station optimizador` y `station msg`: consultan eventos, consumo, contexto y mensajes.

El principal nunca ejecuta `station correr` antes de aprobación. Presenta primero una tarjeta en bloque cercado `propuesta` con JSON `{ "id", "funcion", "modelo_recomendado", "alternativas", "motivo", "tarea" }`; espera la decisión y ejecuta solo después de aprobar.

Para programar se usa la función `constructor`; para revisar, `revisor`; para contexto, `contextualizador`. Los perfiles de permisos se asignan a funciones en `permisos.toml`.
