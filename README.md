# piloto-score — Score Operacional de Pilotos (0.0–5.0)

Motor local, parametrizable y auditable para puntuar pilotos en **B2B**, **Rent** y **B2C**.
La metodología completa (fórmulas, tratamiento de casos, ejemplos, riesgos) está en
[`docs/METODOLOGIA.md`](docs/METODOLOGIA.md).

```
config/parametros.yaml   cómo se mide cada variable (semividas, topes, p0, m, rampas, n_min, bandas, α)
config/pesos.yaml        pesos por tipo — PROPUESTA PRELIMINAR, independientes de la metodología
config/reglas.yaml       reglas existentes → bloqueo / tope / alerta (nunca puntos)
score/engine.py          motor: primitivas + sub-scores + agregación + reglas
score/io.py              carga de CSV/YAML
score/cli.py             python3 -m score …
score/web.py + web.html  afinador local (sliders de pesos, editor de parámetros, desglose)
data/*.csv               11 pilotos ficticios que cubren los casos especiales
tests/test_engine.py     19 pruebas (rango 0–5, casos especiales, no doble conteo…)
sql/extraccion_clickhouse.sql  esqueleto para alimentar data/ desde picapmongoprod (sin verificar)
docs/generar_ejemplos.py       regenera las tablas de ejemplo del doc con el motor real
```

## Uso

```bash
cd ~/dev/piloto-score
python3 -m score                        # ranking de todos los pilotos (fecha de corte: hoy)
python3 -m score --hoy 2026-09-15       # fecha de corte fija (los ejemplos del doc usan esta)
python3 -m score --tipo RENT            # sólo un tipo
python3 -m score --explicar P005        # desglose variable por variable
python3 -m score --json > salida.json   # para Power BI / pruebas
python3 -m score.web                    # afinador en http://127.0.0.1:8765
python3 -m unittest discover -s tests   # pruebas
```

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

`data/pilotos.csv` (una fila por piloto × tipo, ventana de 90 días), `data/eventos.csv`
(una fila por evento disciplinario, con fecha y si sigue activo) y `data/reglas_activas.csv`
(reglas disparadas por piloto). Columnas vacías = dato no disponible (≠ 0), salvo los
conteos básicos de servicios, que vacíos valen 0.
