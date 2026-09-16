# piloto-score — Score Operacional de Pilotos (0.0–5.0)

Motor local, parametrizable y auditable para puntuar pilotos en **B2B**, **Rent** y **B2C**.
**Cuenta de confianza**: `SCORE = base ganada (experiencia + antigüedad, 0 → 3.5; el
recién activado arranca en 0.0) + lo que hace MEJOR que la referencia de su tipo (hasta
+1.5, en proporción a la evidencia) − lo que hace PEOR y sus antecedentes (hasta −3.5)`.
Sin novedades, recaudo (pagado en 24 h y **entregado bien**), alto valor, reservas y la
**calificación de los pasajeros** son **mixtas** (la misma variable suma o resta); suspensiones, invitaciones, expulsión, IMEI, conducta
inapropiada confirmada y activación express **sólo restan**. Además calcula el **cupo de
confianza en plata** (cuánto valor declarado / recaudo se le puede confiar).
La metodología completa (fórmulas, tratamiento de casos, ejemplos, riesgos) está en
[`docs/METODOLOGIA.md`](docs/METODOLOGIA.md).

```
config/parametros.yaml   cómo se mide cada variable (semividas, topes, p0, m, rampas, n_min, bandas, α)
config/pesos.yaml        pesos por tipo — DEFINITIVOS (2026-09-16): el afinador los muestra pero no los edita
config/reglas.yaml       reglas existentes → bloqueo / tope / alerta (nunca puntos)
score/engine.py          motor: primitivas + sub-scores + agregación + reglas
score/io.py              carga de CSV/YAML
score/cli.py             python3 -m score …
score/web.py + web.html  afinador local "Gamification Picap + Pibox" (ranking, desglose, editor de parámetros; pesos fijos)
score/static/            logos de Picap y Pibox que usa la barra del afinador
data/*.csv               12 casos con nombre + 120 pilotos ficticios (data/generar_datos_ficticios.py)
tests/test_engine.py     22 pruebas (rango 0–5, casos especiales, horas hábiles, no doble conteo…)
sql/extraccion_clickhouse.sql  esqueleto para alimentar data/ desde picapmongoprod (sin verificar)
docs/generar_ejemplos.py       regenera las tablas de ejemplo del doc con el motor real
```

## Para arrancar (día a día)

```
cd ~/dev/piloto-score
./arrancar.sh              # levanta el afinador en http://127.0.0.1:8765 y abre el navegador
./refrescar_datos.sh       # (opcional) baja los datos reales de ClickHouse; pide la clave una vez
./arrancar.sh parar        # lo apaga
./arrancar.sh test         # corre las pruebas
```

`refrescar_datos.sh` corre las 6 extracciones de `sql/` (y antes el refresh de
`dashboard_conducta_listas`); acepta números para correr sólo algunas: `./refrescar_datos.sh 01 06`.

## Uso

```bash
cd ~/dev/piloto-score
python3 -m score
python3 -m score --hoy 2026-09-15
python3 -m score --tipo RENT
python3 -m score --explicar P005
python3 -m score --tipo B2B --top 10
python3 -m score --json > salida.json
python3 -m score.web
python3 -m unittest discover -s tests
```

| Comando | Qué hace |
|---|---|
| `python3 -m score` | ranking de todos los pilotos (fecha de corte: hoy) |
| `--hoy 2026-09-15` | fecha de corte fija (los ejemplos del doc usan esta) |
| `--tipo RENT` | sólo un tipo |
| `--explicar P005` | desglose variable por variable |
| `--top 10` | los 10 mejores, 10 del medio y 10 peores, con IDs, activaciones, gamification/app y observaciones |
| `--json` | salida para Power BI / pruebas |
| `python3 -m score.web` | afinador en http://127.0.0.1:8765 (Ctrl+C para cerrarlo) |
| `python3 -m unittest discover -s tests` | pruebas |

⚠️ En esta terminal zsh los `# comentarios` al final de un comando NO se ignoran: se
pasan como argumentos. Escribir el comando solo.

Requiere Python 3 con `PyYAML` (ya instalados en este Mac). Sin otras dependencias.

## Cómo se agregan cosas

- **Otra variable**: sub-score en `engine.sub_scores` (devolver 0–5 o `None`), su bloque
  (`EVENTOS` = antecedentes; el resto = desempeño), su entrada en `aplicabilidad`, sus
  parámetros en `parametros.yaml`, su peso en `pesos.yaml`, una prueba en `tests/`.
- **Otra regla**: una entrada en `reglas.yaml` con `efecto` (`bloqueo|tope|alerta`) y, si el
  score ya mide la misma conducta, `mide_score: <variable>` para que quede como alerta.
- **Otro filtro/segmento**: filtrar `data/pilotos.csv` (o la extracción SQL); el motor no
  necesita cambios — se evalúa por `piloto × tipo`.

## Datos de entrada

`data/pilotos.csv` (una fila por piloto × tipo, ventana de 90 días más las columnas de
ventana propia `vc_*` —cancelación a 6 meses— y `vn_*` —sin novedades a 1 año—; incluye contexto:
`driver_id`, `passenger_id`, activaciones, `calif_gamification`, `calif_app` — este último
sólo contexto: NO es el promedio de lo que ponen los pasajeros; lo que puntúa son
`n_calificados` / `suma_calificaciones`, notas 1–5 en finalizados de 180 días),
`data/eventos.csv` (una fila por evento disciplinario, con fecha y si sigue activo),
`data/recaudos.csv` (un recaudo contra entrega por fila, **todos** desde 2026-09-16:
`fecha_recaudo`, `monto`, `fecha_abono` —primera pata positiva del booking, la usa
`recaudo_24h`— y `fecha_saldado` —la billetera Picash volvió a ≥ 0, la usa
`recaudo_entregado`; vacío = sigue en rojo) y `data/reglas_activas.csv` (reglas disparadas). Columnas vacías = dato no disponible (≠ 0), salvo los
conteos básicos de servicios, que vacíos valen 0.

## Datos reales (ClickHouse → `data_real/`)

Tres consultas, una por comando (piden la clave de `dperilla`); cada una deja su CSV en
`data_real/`. Después `python3 -m score --datos data_real --top 10` o elegir
**REALES (data_real)** en el afinador.

```
curl -sS --fail-with-body -w '→ HTTP %{http_code}\n' "https://clickhouse.picap.io:8443/?database=picapmongoprod" --user dperilla --data-binary @/Users/pibox/dev/piloto-score/sql/01_pilotos.sql -o /Users/pibox/dev/piloto-score/data_real/pilotos.csv
curl -sS --fail-with-body -w '→ HTTP %{http_code}\n' "https://clickhouse.picap.io:8443/?database=picapmongoprod" --user dperilla --data-binary @/Users/pibox/dev/piloto-score/sql/02_eventos.sql -o /Users/pibox/dev/piloto-score/data_real/eventos.csv
curl -sS --fail-with-body -w '→ HTTP %{http_code}\n' "https://clickhouse.picap.io:8443/?database=picapmongoprod" --user dperilla --data-binary @/Users/pibox/dev/piloto-score/sql/03_recaudos.sql -o /Users/pibox/dev/piloto-score/data_real/recaudos.csv
```

Los CSV reales están en `.gitignore`. Supuestos de la extracción (a confirmar) están
comentados al inicio de cada `sql/0*.sql`; `sql/00_descubrir_suspensiones.sql` sirve
para completar el histórico de suspensiones e invitaciones. `sql/calibracion_calificacion.sql`
da los percentiles del promedio de calificación por tipo para fijar `p0` / rampa de
`calificacion_pasajero` en `config/parametros.yaml`.

### Documentos (RUNT / Policía / SOAT) e historial de suspensiones

```
curl -sS --fail-with-body -w '→ HTTP %{http_code}\n' "https://clickhouse.picap.io:8443/?database=picapmongoprod" --user dperilla --data-binary @/Users/pibox/dev/piloto-score/sql/04_documentos.sql -o /Users/pibox/dev/piloto-score/data_real/documentos.csv
curl -sS --fail-with-body -w '→ HTTP %{http_code}\n' "https://clickhouse.picap.io:8443/?database=picapmongoprod" --user dperilla --data-binary @/Users/pibox/dev/piloto-score/sql/05_suspensiones.sql -o /Users/pibox/dev/piloto-score/data_real/eventos_suspensiones.csv
```

```
curl -sS --fail-with-body -w '→ HTTP %{http_code}\n' "https://clickhouse.picap.io:8443/?database=picapmongoprod" --user dperilla --data-binary @/Users/pibox/dev/piloto-score/sql/06_conducta.sql -o /Users/pibox/dev/piloto-score/data_real/eventos_conducta.csv
```

`eventos_conducta.csv`: casos de acoso/hostigamiento **confirmados** ("Con Novedad") del
módulo Conducta Inapropiada, un evento por piloto y día → variable `conducta_inapropiada`.
`documentos.csv` alimenta la capa de habilitación (no da puntos: restringe/alerta según
`parametros.yaml → documentos`). `eventos_suspensiones.csv` trae el historial con fecha de
`driver_suspensions`; el motor descarta el flag sin fecha de `02_eventos` cuando hay historial.
