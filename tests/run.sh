#!/usr/bin/env bash
# Pruebas de las herramientas de agentes (sin Hyprland ni Claude). Uso: tests/run.sh
set -u
B="$(cd "$(dirname "$0")/../agentes/bin" && pwd)"
T="$(mktemp -d)"; export AGENTES_HOME="$T"; trap 'rm -rf "$T"' EXIT
fallos=0
ok()  { echo "ok   $1"; }
mal() { echo "FALLA $1"; fallos=$((fallos+1)); }
chk() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else mal "$d"; fi; }
no()  { local d="$1"; shift; if "$@" >/dev/null 2>&1; then mal "$d"; else ok "$d"; fi; }

$B/tareas add "A" -p t --para x >/dev/null; $B/tareas add "B" -p t --dep 1 >/dev/null
no  "tareas: dependencia sin cumplir"        $B/tareas tomar 2 -p t --como y
no  "tareas: asignada a otro agente"         $B/tareas tomar 1 -p t --como y
chk "tareas: tomar la propia"                $B/tareas tomar 1 -p t --como x
no  "tareas: ya tomada por otro"             $B/tareas tomar 1 -p t --como y
chk "tareas: listo"                          $B/tareas listo 1 -p t
chk "tareas: ahora sí la dependiente"        $B/tareas tomar 2 -p t --como y
$B/tareas add "U" -p r >/dev/null
g=0; for i in $(seq 8); do $B/tareas tomar 1 -p r --como a$i >/dev/null 2>&1 && g=$((g+1)) & done; wait
n=$($B/tareas ls -p r --estado en_curso | wc -l); [ "$n" = 1 ] && ok "tareas: carrera, un solo ganador" || mal "tareas: carrera ($n)"

chk "bloqueo: tomar"                         $B/bloqueo tomar /tmp/zz/a --como a
no  "bloqueo: choque de otro agente"         $B/bloqueo tomar /tmp/zz/a --como b
no  "bloqueo: un directorio cubre sus archivos" $B/bloqueo tomar /tmp/zz --como b
j='{"tool_input":{"file_path":"/tmp/zz/a"}}'
no  "bloqueo hook: bloquea a otro (exit 2)"  bash -c "echo '$j' | AGENTE=b $B/bloqueo hook"
chk "bloqueo hook: deja pasar al dueño"      bash -c "echo '$j' | AGENTE=a $B/bloqueo hook"
chk "bloqueo hook: sin \$AGENTE no hace nada" bash -c "echo '$j' | env -u AGENTE $B/bloqueo hook"

mkdir -p "$T/contexto" "$T/src"; ( cd "$T/src" && git init -q && echo 1 >f && git add f && git -c user.name=t -c user.email=t@t commit -qm 1 )
h=$(git -C "$T/src" rev-parse --short HEAD)
printf '<!-- git HEAD: %s -->\n' "$h" > "$T/contexto/m.md"
printf '# i\nm.md | %s | 2026-01-01 | ~1 | x\n' "$T/src" > "$T/contexto/INDEX.md"
chk "contexto-check: vigente"                $B/contexto-check
( cd "$T/src" && echo 2 >>f && git -c user.name=t -c user.email=t@t commit -qam 2 )
no  "contexto-check: detecta fuente cambiada" $B/contexto-check

mkdir -p "$T/codex"; sed "s#__HOME__#$T#g" "$B/../../config/codex/backend.config.toml" > "$T/codex/backend.config.toml"
no  "equipo: sin equipo.conf falla"          $B/equipo mias
chk "equipo: ayuda"                          $B/equipo -h

# hyprd: traducción de dispatchers clásicos a Lua (sin Hyprland: HYPRD_LUA fuerza el modo Lua, HYPRD_DRY solo imprime)
HD="$(dirname "$B")/../bin/hyprd"
hd() { HYPRD_LUA=1 HYPRD_DRY=1 "$HD" "$@"; }
eq() { if [ "$2" = "$3" ]; then ok "$1"; else mal "$1 ($2)"; fi; }
eq "hyprd: focuswindow"   "$(hd focuswindow 'class:^agente-x$')" 'hl.dsp.focus({ window = [==[class:^agente-x$]==] })'
eq "hyprd: closewindow"   "$(hd closewindow 'class:^agente-x$')" 'hl.dsp.window.close({ window = [==[class:^agente-x$]==] })'
eq "hyprd: workspace"     "$(hd workspace 3)" 'hl.dsp.focus({ workspace = 3 })'
eq "hyprd: exec con reglas" "$(hd exec "[workspace 2 silent] kitty -d '/tmp'")" "hl.dsp.exec_cmd([==[kitty -d '/tmp']==], { workspace = [==[2 silent]==] })"
eq "hyprd: sendshortcut"  "$(hd sendshortcut ', Return, address:0x1')" 'hl.dsp.send_shortcut({ mods = [==[]==], key = [==[Return]==], window = [==[address:0x1]==] })'
no  "hyprd: dispatcher desconocido falla"    hd nada

echo; [ "$fallos" = 0 ] && echo "todo ok" || { echo "$fallos fallos"; exit 1; }
