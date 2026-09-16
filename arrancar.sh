#!/bin/zsh
# Arranca el afinador del Score de Pilotos en http://127.0.0.1:8765
#   ./arrancar.sh            → arranca (o reinicia) y abre el navegador; pide la clave de ClickHouse
#   ./arrancar.sh csv        → arranca sin ClickHouse (sólo CSV locales)
#   ./arrancar.sh parar      → lo apaga
#   ./arrancar.sh test       → corre las pruebas
set -e
cd "$(dirname "$0")"
case "${1:-}" in
  parar)
    pkill -f "score.web" 2>/dev/null && echo "Afinador apagado." || echo "No estaba corriendo."
    exit 0 ;;
  test)
    python3 -m unittest discover -s tests
    exit 0 ;;
esac
# ClickHouse en vivo: si CH_PASSWORD no viene del entorno se pide acá (Enter = seguir
# sólo con los CSV locales). La clave queda sólo en el proceso del afinador.
if [ -z "${CH_PASSWORD:-}" ] && [ "${1:-}" != "csv" ]; then
  printf 'Clave de ClickHouse (dperilla) — Enter para modo CSV: '; read -s CH_PASSWORD; echo
  export CH_PASSWORD
fi
pkill -f "score.web" 2>/dev/null || true
nohup python3 -m score.web > /tmp/piloto-score-web.log 2>&1 &
sleep 1.5
if curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/ | grep -q 200; then
  echo "Afinador corriendo en http://127.0.0.1:8765"
  [ -d data_real ] && [ -f data_real/pilotos.csv ] && echo "Datos reales: $(( $(wc -l < data_real/pilotos.csv) - 1 )) filas (data_real/pilotos.csv, $(stat -f '%Sm' -t '%Y-%m-%d %H:%M' data_real/pilotos.csv))"
  open http://127.0.0.1:8765
else
  echo "No arrancó. Log:"; tail -20 /tmp/piloto-score-web.log; exit 1
fi
