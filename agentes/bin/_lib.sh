# Funciones compartidas. ROOT = ~/agentes (o $AGENTES_HOME)
ROOT="${AGENTES_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CONF="$ROOT/agentes.conf"
ESTADO="$ROOT/estado"

# agente_linea <nombre> -> imprime la línea del conf, o falla
agente_linea() {
  grep -v '^[[:space:]]*#' "$CONF" | awk -F'|' -v n="$1" '$1==n {print; found=1} END{exit !found}'
}
# nombres de todos los agentes
agente_nombres() {
  grep -v '^[[:space:]]*#' "$CONF" | awk -F'|' 'NF>=3 {print $1}'
}
# agente_opcion <nombre> <clave> -> valor de la clave en el 4º campo ("model=haiku,worktree=1"), o vacío
agente_opcion() {
  local linea; linea="$(agente_linea "$1")" || return 0
  awk -F'|' '{print $4}' <<<"$linea" | tr ',' '\n' | awk -F= -v k="$2" '$1==k {print $2; exit}'
}
# ventana abierta del agente (JSON de hyprctl) o vacío
agente_ventana() {
  hyprctl clients -j | jq -c --arg c "agente-$1" '.[] | select(.class==$c)' | head -n1
}
# registro de agentes abiertos (sobrevive a un apagado; lo usa `restaurar`)
registro_abiertos() { echo "$ESTADO/abiertos.json"; }
registro_set() {   # registro_set <nombre> <workspace>
  mkdir -p "$ESTADO"; local f; f="$(registro_abiertos)"; [ -s "$f" ] || echo '{}' > "$f"
  jq --arg n "$1" --arg w "$2" '.[$n]={workspace:$w,ts:(now|floor)}' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
}
registro_del() {   # registro_del <nombre>
  local f; f="$(registro_abiertos)"; [ -s "$f" ] || return 0
  jq --arg n "$1" 'del(.[$n])' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
}
