# Voz

El usuario escucha mis respuestas con un TTS local. Un hook lee en voz alta SOLO lo que esté dentro de `<voz>...</voz>`.

- Al PRINCIPIO de cada respuesta (la primera línea, antes de cualquier otro texto o herramienta), escribí `<voz>...</voz>` con 1 o 2 frases cortas, **siempre en inglés** (la voz es inglesa), naturales y conversacionales. El resto de la respuesta sigue en tu idioma habitual.
- Dentro de `<voz>` nunca va código, rutas, comandos, URLs, listas ni markdown. Describilos ("el script de la voz").
- La voz resume lo importante: qué hice, qué resultado hubo, o qué necesito que decida.
- Si la respuesta es trivial, una sola frase breve.
- Si necesito que el usuario haga algo (p. ej. correr un comando con `!`), la voz lo avisa sin leer el comando.
- La etiqueta va una sola vez, en la primera línea del mensaje.
