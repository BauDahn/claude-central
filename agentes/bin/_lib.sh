# Funciones compartidas. ROOT = ~/agentes
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$ROOT/agentes.conf"

# agente_linea <nombre> -> imprime la línea del conf, o falla
agente_linea() {
  grep -v '^[[:space:]]*#' "$CONF" | awk -F'|' -v n="$1" '$1==n {print; found=1} END{exit !found}'
}
# nombres de todos los agentes
agente_nombres() {
  grep -v '^[[:space:]]*#' "$CONF" | awk -F'|' 'NF>=3 {print $1}'
}
# ventana abierta del agente (JSON de hyprctl) o vacío
agente_ventana() {
  hyprctl clients -j | jq -c --arg c "agente-$1" '.[] | select(.class==$c)' | head -n1
}
