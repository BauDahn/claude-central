#!/usr/bin/env bash
# Instala Claude Central: voz (TTS + dictado), lanzador de agentes y el Claude coordinador.
# Seguro de re-ejecutar. Hace copia de seguridad de ~/.claude/settings.json antes de tocarlo.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VOICE_DIR="$HOME/.local/share/claude-voice"
BIN="$HOME/.local/bin"
SKIP_MODELS="${SKIP_MODELS:-0}"

for c in python3 git claude; do command -v "$c" >/dev/null || { echo "Falta '$c'"; exit 1; }; done
for c in hyprctl wtype pactl parec paplay kitty jq; do
  command -v "$c" >/dev/null || echo "Aviso: no encontré '$c' (necesario para parte de las funciones, ver README)"
done

echo "→ Voz en $VOICE_DIR"
mkdir -p "$VOICE_DIR" "$BIN"
cp "$HERE"/voice/*.py "$HERE"/voice/interactive.md "$VOICE_DIR"/
[ -d "$VOICE_DIR/venv" ] || python3 -m venv "$VOICE_DIR/venv"
"$VOICE_DIR/venv/bin/pip" install -q --upgrade pip
"$VOICE_DIR/venv/bin/pip" install -q kokoro-onnx faster-whisper numpy soundfile
if [ "$SKIP_MODELS" != 1 ]; then
  mkdir -p "$VOICE_DIR/models"
  base="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
  for f in kokoro-v1.0.onnx voices-v1.0.bin; do
    [ -s "$VOICE_DIR/models/$f" ] || curl -L --fail -o "$VOICE_DIR/models/$f" "$base/$f"
  done
fi

echo "→ Comandos en $BIN"
install -m755 "$HERE/bin/central" "$HERE/bin/escucha" "$BIN/"

echo "→ Agentes en ~/agentes"
mkdir -p "$HOME/agentes"
cp -r "$HERE/agentes/roles" "$HERE/agentes/bin" "$HOME/agentes/"
install -m755 "$HERE/agentes/lanzar" "$HERE/agentes/cerrar" "$HERE/agentes/listar" "$HOME/agentes/"
[ -f "$HOME/agentes/agentes.conf" ] || cp "$HERE/agentes/agentes.conf.example" "$HOME/agentes/agentes.conf"
chmod +x "$HOME/agentes/bin/_run"

echo "→ Claude coordinador en ~/central"
mkdir -p "$HOME/central"
[ -f "$HOME/central/CLAUDE.md" ] || cp "$HERE/central/CLAUDE.md" "$HOME/central/CLAUDE.md"
install -m755 "$HERE/central/hoy" "$HOME/central/hoy"

echo "→ Instrucciones globales de voz (~/.claude/CLAUDE.md)"
mkdir -p "$HOME/.claude"
if ! grep -q '<voz>' "$HOME/.claude/CLAUDE.md" 2>/dev/null; then
  { echo; cat "$HERE/config/CLAUDE.global.md"; } >> "$HOME/.claude/CLAUDE.md"
else echo "  ya tiene sección de voz, no la toco"; fi

echo "→ Hooks en ~/.claude/settings.json"
S="$HOME/.claude/settings.json"; [ -f "$S" ] || echo '{}' > "$S"
cp "$S" "$S.bak-claude-central-$(date +%s)"
VOICE_DIR="$VOICE_DIR" HOOKS="$HERE/config/hooks.json" SETTINGS="$S" python3 - <<'PY'
import json, os
d = os.environ["VOICE_DIR"]; py = d + "/venv/bin/python"
hooks = json.loads(open(os.environ["HOOKS"]).read().replace("$VOICE_PY", py).replace("$VOICE_DIR", d))
p = os.environ["SETTINGS"]; s = json.load(open(p)); h = s.setdefault("hooks", {})
for ev, entries in hooks.items():
    cur = h.setdefault(ev, [])
    for e in entries:
        if not any(d + "/voice.py" in str(c) for c in cur):
            cur.append(e)
json.dump(s, open(p, "w"), indent=2, ensure_ascii=False)
PY
echo
echo "Listo. Probalo:  $VOICE_DIR/venv/bin/python $VOICE_DIR/voice.py say \"hello\""
echo "Coordinador:     central     |  Escucha: escucha on     |  Agentes: ~/agentes/lanzar <nombre>"
echo "Asegurate de que ~/.local/bin esté en tu PATH."
