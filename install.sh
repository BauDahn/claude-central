#!/usr/bin/env bash
# Instala Claude Central: voz (TTS + dictado), lanzador de agentes y el Claude coordinador.
# Seguro de re-ejecutar. Hace copia de seguridad de ~/.claude/settings.json antes de tocarlo.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VOICE_DIR="$HOME/.local/share/claude-voice"
BIN="$HOME/.local/bin"
SKIP_MODELS="${SKIP_MODELS:-0}"
SKIP_VENV="${SKIP_VENV:-0}"   # 1 = no crear el venv ni instalar dependencias de voz (útil para tests/CI)

for c in python3 git claude; do command -v "$c" >/dev/null || { echo "Falta '$c'"; exit 1; }; done
for c in hyprctl wtype pactl parec paplay kitty jq; do
  command -v "$c" >/dev/null || echo "Aviso: no encontré '$c' (necesario para parte de las funciones, ver README)"
done

echo "→ Voz en $VOICE_DIR"
mkdir -p "$VOICE_DIR" "$BIN"
cp "$HERE"/voice/*.py "$HERE"/voice/interactive.md "$VOICE_DIR"/
if [ "$SKIP_VENV" != 1 ]; then
  [ -d "$VOICE_DIR/venv" ] || python3 -m venv "$VOICE_DIR/venv"
  "$VOICE_DIR/venv/bin/pip" install -q --upgrade pip
  "$VOICE_DIR/venv/bin/pip" install -q kokoro-onnx faster-whisper numpy soundfile
fi
if [ "$SKIP_MODELS" != 1 ] && [ "$SKIP_VENV" != 1 ]; then
  mkdir -p "$VOICE_DIR/models"
  base="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
  for f in kokoro-v1.0.onnx voices-v1.0.bin; do
    [ -s "$VOICE_DIR/models/$f" ] || curl -L --fail -o "$VOICE_DIR/models/$f" "$base/$f"
  done
fi

echo "→ Comandos en $BIN"
install -m755 "$HERE/bin/escucha" "$BIN/"
if command -v uv >/dev/null; then
  uv tool install --force --editable "$HERE[ui]" >/dev/null && echo "  central (CLI Python) instalado con uv"
else
  echo "  Aviso: falta uv (https://docs.astral.sh/uv/); sin él no se instala el comando central"
fi

echo "→ Agentes en ~/agentes"
if [ "$(readlink -f "$HOME/agentes" 2>/dev/null)" = "$(readlink -f "$HERE/agentes")" ]; then
  echo "  ~/agentes ya es un enlace a este repo; no hay nada que copiar"
else
  mkdir -p "$HOME/agentes"
  cp -r "$HERE/agentes/roles" "$HERE/agentes/bin" "$HOME/agentes/"
  [ -d "$HOME/agentes/contexto" ] || cp -r "$HERE/agentes/contexto" "$HOME/agentes/"
  install -m755 "$HERE/agentes/lanzar" "$HERE/agentes/cerrar" "$HERE/agentes/listar" "$HERE/agentes/restaurar" "$HERE/agentes/guardar-estado" "$HOME/agentes/"
  chmod +x "$HOME/agentes/bin/"*
fi
mkdir -p "$HOME/agentes/estado" "$HOME/agentes/tareas" "$HOME/agentes/locks"
for t in tareas bloqueo tokens compactar contexto-check equipo bitacora sub sublog reportar; do ln -sf "$HOME/agentes/bin/$t" "$BIN/$t"; done
mkdir -p "$HOME/.config/systemd/user"
cp "$HERE"/config/systemd/guardar-estado.* "$HOME/.config/systemd/user/"
if command -v systemctl >/dev/null; then
  systemctl --user daemon-reload && systemctl --user enable --now guardar-estado.timer >/dev/null 2>&1 || echo "  Aviso: no pude activar el timer de guardar-estado"
fi
[ -f "$HOME/agentes/agentes.conf" ] || cp "$HERE/agentes/agentes.conf.example" "$HOME/agentes/agentes.conf"
chmod +x "$HOME/agentes/bin/_run"

echo "→ Claude coordinador en ~/central"
mkdir -p "$HOME/central"
[ -f "$HOME/central/CLAUDE.md" ] || cp "$HERE/central/CLAUDE.md" "$HOME/central/CLAUDE.md"
install -m755 "$HERE/central/hoy" "$HOME/central/hoy"
grep -q 'equipo:inicio' "$HOME/central/CLAUDE.md" || { echo; cat "$HERE/config/central-equipo.md"; } >> "$HOME/central/CLAUDE.md"

echo "→ Perfiles de Codex por rol (~/.codex, para central correr)"
if [ -d "$HOME/.codex" ] || command -v codex >/dev/null; then
  mkdir -p "$HOME/.codex"
  for f in "$HERE"/config/codex/*.config.toml; do
    dest="$HOME/.codex/$(basename "$f")"
    [ -f "$dest" ] || sed "s#__HOME__#$HOME#g" "$f" > "$dest"
  done
else
  echo "  Codex no está instalado: salteo (npm i -g @openai/codex && codex login, y re-ejecutá el instalador)"
fi

echo "→ Instrucciones globales de voz (~/.claude/CLAUDE.md)"
mkdir -p "$HOME/.claude"
if ! grep -q '<voz>' "$HOME/.claude/CLAUDE.md" 2>/dev/null; then
  { echo; cat "$HERE/config/CLAUDE.global.md"; } >> "$HOME/.claude/CLAUDE.md"
else echo "  ya tiene sección de voz, no la toco"; fi

echo "→ Hooks en ~/.claude/settings.json"
S="$HOME/.claude/settings.json"; [ -f "$S" ] || echo '{}' > "$S"
cp "$S" "$S.bak-claude-central-$(date +%s)"
VOICE_DIR="$VOICE_DIR" AGENTES_DIR="$HOME/agentes" HERE="$HERE" SETTINGS="$S" python3 - <<'PY'
import json, os
d = os.environ["VOICE_DIR"]; a = os.environ["AGENTES_DIR"]; here = os.environ["HERE"]
def cargar(nombre):
    t = open(f"{here}/config/{nombre}").read()
    return json.loads(t.replace("$VOICE_PY", d + "/venv/bin/python").replace("$VOICE_DIR", d).replace("$AGENTES_DIR", a))
p = os.environ["SETTINGS"]; s = json.load(open(p)); h = s.setdefault("hooks", {})
for nombre in ("hooks.json", "hooks-agentes.json"):
    for ev, entries in cargar(nombre).items():
        cur = h.setdefault(ev, [])
        for e in entries:
            cmd = e["hooks"][0]["command"]
            if not any(cmd == x.get("command") for c in cur for x in c.get("hooks", [])):
                cur.append(e)
json.dump(s, open(p, "w"), indent=2, ensure_ascii=False)
PY
echo
echo "Listo. Probalo:  $VOICE_DIR/venv/bin/python $VOICE_DIR/voice.py say \"hello\""
echo "Coordinador:     central     |  Escucha: escucha on     |  Agentes: ~/agentes/lanzar <nombre>"
echo "Codex:           central roles    |  Equipo multi-máquina: equipo init --maquina <nombre> --rol orquestador|miembro --repo <dueño/repo> --dir <proyecto>"
echo "Opcional (guardado automático del estado cada 10 min): systemctl --user enable --now guardar-estado.timer"
echo "Opcional (reabrir agentes al iniciar sesión):          exec-once = ~/agentes/restaurar   (en hyprland.conf)"
echo "Asegurate de que ~/.local/bin esté en tu PATH."
