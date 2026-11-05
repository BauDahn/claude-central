# Spotify para el subagente dj

Script: `~/agentes/spotify/venv/bin/python ~/agentes/spotify/spotify.py <comando>` (solo stdlib; el venv es solo el intérprete).
Credenciales (fuera del repo): `~/.config/spotify-dj/credentials.json`. Token: `~/.config/spotify-dj/token.json` (600).

## Pasos para el usuario (una sola vez)
1. Entrar a https://developer.spotify.com/dashboard con su cuenta Premium y aceptar los términos.
2. "Create app": nombre y descripción libres.
3. Redirect URI: `http://127.0.0.1:8888/callback` (exacta, con 127.0.0.1, no "localhost"). Añadir y guardar.
4. APIs/SDKs a marcar: "Web API".
5. Guardar; en Settings copiar Client ID y Client secret (View client secret).
6. Crear `~/.config/spotify-dj/credentials.json` (hay un `.example` al lado) con `{"client_id": "...", "client_secret": "..."}` y `chmod 600` sobre él.
7. En Settings > User Management, añadir su propio email (modo desarrollo solo deja usar la app a usuarios listados).
8. Correr `spotify.py login`: abre el navegador, aceptar permisos; el token se guarda solo.

## Comandos
playlists | artists | search <texto> [--tipo track|album|artist|playlist] | find <texto> (catálogo) |
play <uri|texto> | queue <uri|texto> | now | pause | resume | next | prev | volume N

`search`/`play` con texto buscan solo en la biblioteca guardada, playlists y artistas seguidos (sin recomendaciones).
Reproducir usa la API sobre el dispositivo "Computer" y, si falla, `playerctl open`.
