#!/bin/zsh
# Baja de ClickHouse todos los CSV reales a data_real/ (pide la clave de dperilla UNA vez).
#   ./refrescar_datos.sh              → todo
#   ./refrescar_datos.sh 01 03        → sólo esas consultas
# Antes refresca la tabla de listas de Conducta Inapropiada (de la que sale 06).
set -e
cd "$(dirname "$0")"
CH="https://clickhouse.picap.io:8443/?database=picapmongoprod"
mkdir -p data_real
printf 'Clave de dperilla: '; read -s PASS; echo
typeset -A SALIDA
SALIDA=(01 pilotos.csv 02 eventos.csv 03 recaudos.csv 04 documentos.csv 05 eventos_suspensiones.csv 06 eventos_conducta.csv)
ORDEN=(01 02 03 04 05 06)
[ $# -gt 0 ] && ORDEN=("$@")

correr() {  # correr <etiqueta> <archivo.sql> [salida]
  local out="${3:-/dev/null}" tmp
  tmp=$(mktemp)
  local code
  code=$(curl -sS -w '%{http_code}' "$CH" --user "dperilla:$PASS" --data-binary @"$2" -o "$tmp")
  if [ "$code" != "200" ]; then
    echo "  ✗ $1 → HTTP $code: $(head -c 400 "$tmp")"; rm -f "$tmp"; return 1
  fi
  if [ "$out" != "/dev/null" ]; then
    mv "$tmp" "$out"; echo "  ✓ $1 → $out ($(( $(wc -l < "$out") - 1 )) filas)"
  else
    rm -f "$tmp"; echo "  ✓ $1"
  fi
}

REFRESH=~/dev/picap-monitoreo-rails/db/clickhouse/dashboard_conducta_listas_refresh.sql
if [[ " ${ORDEN[*]} " == *" 06 "* ]] && [ -f "$REFRESH" ]; then
  echo "Refrescando dashboard_conducta_listas…"
  correr "conducta_listas_refresh" "$REFRESH" || true
fi
echo "Extrayendo…"
for n in "${ORDEN[@]}"; do
  f=$(ls sql/${n}_*.sql 2>/dev/null | head -1)
  [ -z "$f" ] && { echo "  ? no existe sql/${n}_*.sql"; continue; }
  correr "$n $(basename "$f")" "$f" "data_real/${SALIDA[$n]}" || true
done
unset PASS
echo "Listo. El afinador toma los archivos nuevos solo (recargá la página)."
