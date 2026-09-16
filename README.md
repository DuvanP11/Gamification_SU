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
score/web.py             servidor del afinador "Gamification Picap + Pibox" (ranking, desglose, buscador, hoja de vida; pesos fijos)
score/ch.py              ClickHouse en vivo: extracción anclada a la fecha de corte, búsqueda por id/cédula/placa/celular/correo, hoja de vida
index.html + static/     la página y la portada (tinta blanca, fondo transparente); en Vercel se sirven como estáticos
api/index.py             entrada para Vercel: expone el mismo handler como función serverless (ver "Publicar en Vercel")
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

## ClickHouse en vivo (buscador, hoja de vida y ranking por fecha)

Con la clave de `dperilla` en `CH_PASSWORD` (`./arrancar.sh` la pide al arrancar; Enter =
modo CSV) el afinador:

- Ofrece la fuente **ClickHouse (en vivo)**. Al pedir un ranking con una **fecha de corte**
  (o un **mes**: se toma su último día), corre `sql/01..06` con `now()`/`today()`
  reemplazados por esa fecha y deja los CSV en `data_ch/<fecha>/` (caché; "↻ volver a
  extraer" los baja de nuevo). Es exactamente la misma metodología: cambia el ancla de las
  ventanas, no las fórmulas. La primera extracción de una fecha tarda un par de minutos.
- **Buscar piloto** por ID, cédula, placa, celular o correo (mismas condiciones que
  Consulta de Datos del portal): muestra quién es, su score por tipo en la fuente/corte
  elegidos, y dos botones — **Hoja de vida** (ventana emergente con la ficha completa:
  identidad, contacto, estado, bloqueos históricos, última conexión, placas y servicios
  por rol/tipo/estado con rango de fechas) y **Resumen Score** (el desglose).
- `APP_PASSWORD`: si está definida, la página pide una clave y todo `/api/*` la exige.
  **Obligatoria cuando está publicada**: la hoja de vida trae datos personales.

Variables: `CH_URL` (por defecto `https://clickhouse.picap.io:8443/?database=picapmongoprod`),
`CH_USER` (`dperilla`), `CH_PASSWORD`, `APP_PASSWORD`, opcional `CONSULTA_DATOS_COL_PLACA`.

## Publicar en Vercel (web en producción)

El repo es `github.com/DuvanP11/Gamification_SU`. Vercel lo despliega solo con importarlo
(Add New → Project → ese repo; no hay que configurar nada: `vercel.json` ya trae el rewrite
de `/api/*` a la función Python y `requirements.txt` instala PyYAML). Cada push a `main`
publica una versión nueva.

- `index.html` y `static/` se sirven como archivos estáticos; `/api/config`, `/api/score` y
  `/api/detalle` corren en `api/index.py` (el mismo `score.web.H` del afinador local).
- **Datos:** en producción sólo están los ficticios de `data/`. `data_real/*.csv` tiene
  nombres e IDs reales de pilotos y está en `.gitignore`: **no se sube al repo público ni a
  Vercel**. Para publicar con datos reales hacen falta dos cosas que no se pueden decidir
  desde el código: un repo/deploy privado con acceso controlado (Vercel Authentication o
  contraseña) y una forma de subir los CSV sin pasar por git (p. ej. Vercel Blob privado).
- `/api/guardar` responde error en producción (el disco es de sólo lectura): los
  parámetros se cambian en `config/parametros.yaml` con commit y se despliegan.
- **ClickHouse desde Vercel:** definir en el proyecto (Settings → Environment Variables)
  `CH_PASSWORD`, `APP_PASSWORD` (y `CH_USER`/`CH_URL` si cambian). El buscador y la hoja
  de vida son consultas chicas y funcionan; el ranking en vivo extrae ~25 MB y puede
  pasarse del límite de la función (60 s) — en ese caso el ranking se ve con los CSV
  y la búsqueda/hoja de vida siguen en vivo. La caché de extracción vive en `/tmp` y se
  pierde con cada instancia nueva.

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
