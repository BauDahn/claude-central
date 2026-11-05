#!/usr/bin/env python3
"""CLI de Spotify para el subagente dj (solo stdlib, sin dependencias).

Credenciales: ~/.config/spotify-dj/credentials.json  {"client_id": "...", "client_secret": "..."}
Token:        ~/.config/spotify-dj/token.json (permisos 600)

Comandos:
  login                      autorizar la app (abre el navegador, redirect a 127.0.0.1)
  playlists                  playlists del usuario
  artists                    artistas seguidos
  search <texto> [--tipo track|album|artist|playlist|all]
                             busca en la biblioteca guardada y en las playlists del usuario
  find <texto> [--tipo ...]  busca en todo Spotify (catalogo)
  play <uri|texto> [--tipo track|album|playlist]
                             reproduce una URI (spotify:...) o, si es texto, busca en tu biblioteca
  queue <uri|texto>          pone una cancion en cola
  now | pause | resume | next | prev | volume N
Todas las salidas son texto plano: una linea por item, con la URI al final.
"""
import base64, http.server, json, os, secrets, subprocess, sys, time, urllib.parse, urllib.request, urllib.error, webbrowser
from pathlib import Path

CONF = Path.home() / ".config/spotify-dj"
CREDS, TOKEN = CONF / "credentials.json", CONF / "token.json"
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = ("user-library-read playlist-read-private playlist-read-collaborative "
          "user-follow-read user-modify-playback-state user-read-playback-state "
          "user-read-currently-playing")
API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"


def die(msg):
    print(msg, file=sys.stderr); sys.exit(1)


def creds():
    try:
        c = json.loads(CREDS.read_text())
        return c["client_id"], c["client_secret"]
    except (OSError, ValueError, KeyError):
        die(f"Faltan credenciales en {CREDS} (ver LEEME.md).")


def _token_request(data):
    cid, sec = creds()
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    req = urllib.request.Request(ACCOUNTS + "/api/token", urllib.parse.urlencode(data).encode(),
                                 {"Authorization": "Basic " + auth})
    try:
        return json.load(urllib.request.urlopen(req, timeout=15))
    except urllib.error.HTTPError as e:
        die(f"Error de autenticacion: {e.read().decode()}")


def save_token(t, old=None):
    if old and "refresh_token" not in t:
        t["refresh_token"] = old["refresh_token"]
    t["expires_at"] = time.time() + t["expires_in"] - 60
    fd = os.open(TOKEN, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(t, f)
    os.chmod(TOKEN, 0o600)


def login():
    cid, _ = creds()
    state = secrets.token_urlsafe(16)
    url = ACCOUNTS + "/authorize?" + urllib.parse.urlencode(
        {"client_id": cid, "response_type": "code", "redirect_uri": REDIRECT,
         "scope": SCOPES, "state": state})
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Listo, ya podes cerrar esta pestana.".encode())
        def log_message(self, *a): pass

    srv = http.server.HTTPServer(("127.0.0.1", 8888), H)
    srv.timeout = 180
    print("Abri esta URL si no se abre sola:\n" + url, file=sys.stderr)
    webbrowser.open(url)
    srv.handle_request()
    if got.get("state") != state or "code" not in got:
        die(f"Autorizacion fallida: {got.get('error', 'sin codigo')}")
    save_token(_token_request({"grant_type": "authorization_code", "code": got["code"],
                               "redirect_uri": REDIRECT}))
    print("Autorizado. Token guardado en", TOKEN)


def access_token():
    try:
        t = json.loads(TOKEN.read_text())
    except (OSError, ValueError):
        die("No hay token: corre `spotify.py login` primero.")
    if time.time() >= t["expires_at"]:
        t = _refresh(t)
    return t["access_token"]


def _refresh(t):
    n = _token_request({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    save_token(n, t)
    return json.loads(TOKEN.read_text())


def api(method, path, params=None, body=None, ok_empty=False):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(3):
        req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                     {"Authorization": "Bearer " + access_token(),
                                      "Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", "2")) + 1); continue
            msg = e.read().decode()
            if e.code == 404 and "player" in path:
                die("No hay dispositivo de Spotify activo (abri la app de escritorio).")
            die(f"HTTP {e.code} en {method} {path}: {msg}")
    die("Spotify rate limit persistente")


def pages(path, params=None, key=None, limit=50):
    params = dict(params or {}, limit=limit)
    out, url_off = [], 0
    while True:
        d = api("GET", path, dict(params, offset=url_off))
        d = d[key] if key else d
        out += d["items"]
        url_off += limit
        if not d.get("next"):
            return out


# ------------------------------------------------------------ biblioteca
def get_playlists():
    return [p for p in pages("/me/playlists") if p]


def cmd_playlists():
    for p in get_playlists():
        print(f"{p['name']} ({p['tracks']['total'] if 'tracks' in p else '?'} canciones) - {p['uri']}")


def cmd_artists():
    out, after = [], None
    while True:
        d = api("GET", "/me/following", {"type": "artist", "limit": 50, **({"after": after} if after else {})})["artists"]
        out += d["items"]
        after = d.get("cursors", {}).get("after")
        if not after or not d["items"]:
            break
    for a in out:
        print(f"{a['name']} - {a['uri']}")


def fmt_track(t):
    return f"{t['name']} - {', '.join(a['name'] for a in t['artists'])} [{t['album']['name']}] - {t['uri']}"


def norm(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if not unicodedata.combining(c))


def library_search(text, tipo="all"):
    q = norm(text)
    res = []
    if tipo in ("all", "playlist"):
        for p in get_playlists():
            if q in norm(p["name"]):
                res.append(("playlist", f"{p['name']} - {p['uri']}", p["uri"]))
    if tipo in ("all", "track"):
        for it in pages("/me/tracks"):
            t = it["track"]
            if q in norm(t["name"] + " " + " ".join(a["name"] for a in t["artists"]) + " " + t["album"]["name"]):
                res.append(("track", fmt_track(t), t["uri"]))
    if tipo in ("all", "album"):
        for it in pages("/me/albums"):
            a = it["album"]
            if q in norm(a["name"] + " " + " ".join(x["name"] for x in a["artists"])):
                res.append(("album", f"{a['name']} - {', '.join(x['name'] for x in a['artists'])} - {a['uri']}", a["uri"]))
    if tipo in ("all", "artist"):
        out, after = [], None
        while True:
            d = api("GET", "/me/following", {"type": "artist", "limit": 50, **({"after": after} if after else {})})["artists"]
            out += d["items"]; after = d.get("cursors", {}).get("after")
            if not after or not d["items"]: break
        for a in out:
            if q in norm(a["name"]):
                res.append(("artist", f"{a['name']} - {a['uri']}", a["uri"]))
    # playlists propias: canciones dentro
    if tipo in ("all", "track"):
        me = api("GET", "/me")["id"]
        for p in get_playlists():
            if p["owner"]["id"] != me and not p.get("collaborative"):
                continue  # la API solo deja leer items de playlists propias/colaborativas
            try:
                items = pages(f"/playlists/{p['id']}/items", {"fields": "items(track(name,uri,artists(name),album(name))),next"})
            except SystemExit:
                continue
            for it in items:
                t = it.get("track")
                if t and q in norm(t["name"] + " " + " ".join(a["name"] for a in t["artists"])):
                    res.append(("track", fmt_track(t) + f"  (en playlist: {p['name']})", t["uri"]))
    return res


def cmd_search(text, tipo):
    r = library_search(text, tipo)
    if not r:
        print("Sin resultados en tu biblioteca."); return
    seen = set()
    for kind, line, uri in r:
        if (kind, uri) in seen: continue
        seen.add((kind, uri)); print(f"[{kind}] {line}")


def cmd_find(text, tipo):
    types = "track,album,artist,playlist" if tipo == "all" else tipo
    d = api("GET", "/search", {"q": text, "type": types, "limit": 10})
    for t in d.get("tracks", {}).get("items", []): print("[track]", fmt_track(t))
    for a in d.get("albums", {}).get("items", []): print(f"[album] {a['name']} - {', '.join(x['name'] for x in a['artists'])} - {a['uri']}")
    for a in d.get("artists", {}).get("items", []): print(f"[artist] {a['name']} - {a['uri']}")
    for p in d.get("playlists", {}).get("items", []):
        if p: print(f"[playlist] {p['name']} - {p['uri']}")


# ------------------------------------------------------------ reproduccion
def resolve(arg, tipo):
    if arg.startswith("spotify:"):
        return arg
    if "open.spotify.com/" in arg:
        parts = urllib.parse.urlparse(arg).path.strip("/").split("/")
        return f"spotify:{parts[-2]}:{parts[-1]}"
    r = library_search(arg, tipo)
    if not r:
        die(f"No encontre {arg!r} en tu biblioteca. Probá `find` o dame la URI.")
    order = {"playlist": 0, "album": 1, "track": 2, "artist": 3}
    r.sort(key=lambda x: order[x[0]])
    print(f"-> {r[0][1]}", file=sys.stderr)
    return r[0][2]


def local_device():
    devs = api("GET", "/me/player/devices").get("devices", [])
    for d in devs:
        if d["type"] == "Computer":
            return d["id"]
    return devs[0]["id"] if devs else None


def cmd_play(arg, tipo):
    uri = resolve(arg, tipo)
    kind = uri.split(":")[1]
    body = {"uris": [uri]} if kind == "track" else {"context_uri": uri}
    dev = local_device()
    try:
        api("PUT", "/me/player/play", {"device_id": dev} if dev else None, body)
        print("Reproduciendo", uri); return
    except SystemExit:
        pass
    # fallback: Spotify de escritorio por MPRIS
    if subprocess.run(["playerctl", "-p", "spotify", "open", uri]).returncode == 0:
        print("Reproduciendo (playerctl)", uri)
    else:
        die("No pude reproducir: abri Spotify de escritorio.")


def cmd_queue(arg):
    uri = resolve(arg, "track")
    if uri.split(":")[1] != "track":
        die("Solo se pueden poner canciones en cola.")
    dev = local_device()
    api("POST", "/me/player/queue", {"uri": uri, **({"device_id": dev} if dev else {})})
    print("En cola", uri)


def cmd_now():
    d = api("GET", "/me/player/currently-playing")
    if not d or not d.get("item"):
        print("Nada sonando."); return
    print(("Sonando: " if d["is_playing"] else "Pausado: ") + fmt_track(d["item"]))


def player(cmd, *args):
    names = {"pause": "pause", "resume": "play", "next": "next", "prev": "previous"}
    subprocess.run(["playerctl", "-p", "spotify", names[cmd]], check=False)


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return
    tipo = "all"
    if "--tipo" in a:
        i = a.index("--tipo"); tipo = a[i + 1]; del a[i:i + 2]
    cmd, rest = a[0], " ".join(a[1:])
    if cmd == "login": login()
    elif cmd == "playlists": cmd_playlists()
    elif cmd == "artists": cmd_artists()
    elif cmd == "search" and rest: cmd_search(rest, tipo)
    elif cmd == "find" and rest: cmd_find(rest, tipo)
    elif cmd == "play" and rest: cmd_play(rest, tipo)
    elif cmd == "queue" and rest: cmd_queue(rest)
    elif cmd == "now": cmd_now()
    elif cmd in ("pause", "resume", "next", "prev"): player(cmd)
    elif cmd == "volume" and rest.isdigit():
        api("PUT", "/me/player/volume", {"volume_percent": min(100, int(rest))})
    else: die(__doc__)


if __name__ == "__main__":
    main()
