# Score Operacional de Pilotos (0.0 – 5.0) — Metodología

> Versión 0.1 · borrador de trabajo · 2026-09-15.
> Los **pesos y umbrales numéricos son preliminares** y viven en `config/`; la metodología
> (cómo se mide cada cosa) es independiente de ellos. Todo lo que dice este documento está
> implementado en `score/engine.py` y cubierto por `tests/`.

## Definiciones que hay que confirmar con Operaciones (NO inventadas, sólo asumidas)

| Término del requerimiento | Cómo lo trata el modelo | Qué falta confirmar |
|---|---|---|
| Invitaciones Pibox / Rent | Evento disciplinario leve con fecha (llamado de atención / citación) | Qué es exactamente una "invitación" y en qué tabla vive |
| 24 hrs a excepción de un FDS | **Confirmado 2026-09-15:** de cada recaudo contra entrega no abonado en el momento, si lo pagó dentro de 24 h **hábiles** (sábado y domingo no corren) → variable `recaudo_24h` | Fuente: par recaudo (−) / abono (+) en `WalletAccountCounterDeliveryTransaction`; si un vencido sin pagar debe además bloquear |
| Suspensión pasajero | Suspensión de la misma persona en su rol de pasajero | Si Operaciones quiere que pese en el score de piloto o sólo como alerta |
| Servicio "con novedad" / "dentro de los tiempos" | Un flag por servicio finalizado: `ok = sin novedad AND a tiempo` | Catálogo de novedades y el SLA de tiempo por tipo |
| Valor declarado "alto" | `valor_declarado ≥ umbral_valor[tipo]` (parámetro) | Umbral por tipo; se sugiere el percentil 80 de la población |
| Reserva "atribuible al piloto" | Una causa de incumplimiento/cancelación pertenece al catálogo atribuible o no | Catálogo de causas |

---

## 1. Arquitectura general

Tres capas, cada una con una responsabilidad y **sin mezclarse**:

```
                ┌──────────────────────────────────────────────────────────────┐
 datos ──────▶  │ CAPA 1 · SCORE COMPORTAMENTAL (0–5)                          │
 (ventana +     │   sub-score por variable (0–5)  →  D = desempeño (promedio   │
  historial)    │   ponderado)  ×  factor de antecedentes (1 − α·P)            │
                └──────────────────────────────┬───────────────────────────────┘
                                               ▼
                ┌──────────────────────────────────────────────────────────────┐
 reglas ──────▶ │ CAPA 2 · REGLAS DE RIESGO (las que ya existen)               │
 existentes     │   bloqueo · tope · alerta   — nunca suman ni restan puntos   │
                └──────────────────────────────┬───────────────────────────────┘
                                               ▼
                ┌──────────────────────────────────────────────────────────────┐
                │ CAPA 3 · RESULTADO FINAL                                     │
                │   score_final, banda, vigencia (definitivo/provisional),     │
                │   confianza, estado (OK/RESTRINGIDO/BLOQUEADO), alertas,     │
                │   desglose auditable variable por variable                   │
                └──────────────────────────────────────────────────────────────┘
```

**Por qué no es un único `Σ(score × peso)`.** Se probó primero (ver §9). Con esa forma, un
piloto con historial limpio recibe 5.0 en las 5–7 variables de eventos, que representan
~45 % del peso: un desempeño operativo malo queda diluido a "BUENO". Un historial limpio
no es mérito, es *ausencia de demérito*. Por eso los eventos actúan como **descuento
multiplicativo** sobre el desempeño, y el desempeño sí es un promedio ponderado.

Cuatro primitivas matemáticas bastan para todo el modelo (todas con traducción directa
a SQL / Excel / DAX, ver §16):

| Primitiva | Fórmula | Para qué |
|---|---|---|
| `rampa(x, x₀, x₅)` | `5 · clip((x − x₀)/(x₅ − x₀), 0, 1)` | Convertir una tasa a 0–5 con dos umbrales; sirve "más es mejor" y "menos es mejor" |
| `tasa_ajustada(x, n, p₀, m)` | `(x + m·p₀)/(n + m)` | Suavizado bayesiano: amortigua muestras pequeñas hacia la referencia poblacional |
| `decaimiento(edad, H)` | `0.5^(edad/H)` | Peso de un evento por antigüedad (semivida H) |
| `saturación(n, n_ref)` | `clip(ln(1+n)/ln(1+n_ref), 0, 1)` | Volumen con rendimiento decreciente |

## 2. Tabla de variables

| Variable | B2B | RENT | B2C | Naturaleza | Bloque | Indicador |
|---|:-:|:-:|:-:|---|---|---|
| Suspensión piloto | ✓ | ✓ | ✓ | Negativa | Antecedentes | carga con decaimiento |
| Suspensión pasajero | ✓ | ✓ | ✓ | Negativa | Antecedentes | carga con decaimiento |
| Invitaciones Pibox | ✓ | ✓ | ✓ | Negativa | Antecedentes | carga con decaimiento |
| Invitaciones Rent | ✓ | ✓ | ✓ | Negativa | Antecedentes | carga con decaimiento |
| Expulsiones | ✓ | ✓ | ✓ | Negativa + **restricción** si activa | Antecedentes | carga con decaimiento |
| Baneo de IMEI | – | ✓ | – | Negativa + **restricción** si activo | Antecedentes | carga con decaimiento |
| **Conducta inapropiada confirmada** (acoso / hostigamiento) | ✓ | ✓ | ✓ | Negativa | Antecedentes | carga con decaimiento, sólo casos "Con Novedad" |
| Recaudo pagado en 24 h hábiles | ✓ | – | – | Mixta (tasa) + alerta si vencido | Desempeño | tasa de episodios pagados a tiempo, ajustada |
| Servicios que canceló | ✓ | ✓ | ✓ | Mixta (tasa) | Desempeño | tasa de cancelación propia, ajustada |
| Servicios finalizados | ✓ | ✓ | ✓ | Positiva | Desempeño | volumen saturante (experiencia) |
| Servicios totales por tipo | ✓ | ✓ | ✓ | **Contexto** | — | denominadores + confianza (no puntúa) |
| Valor declarado mayor | ✓ | – | ✓ | Mixta | Desempeño | exposición × cumplimiento en alto valor |
| Sin novedades en tiempos | ✓ | – | ✓ | Mixta (tasa) | Desempeño | tasa OK ajustada |
| Incumplimiento de reserva | ✓ | – | – | Mixta (tasa) | Desempeño | tasa de cumplimiento atribuible |
| Reglas existentes | ✓ | ✓ | ✓ | **Restricción / alerta** | Capa 2 | bloqueo / tope / alerta |

Convención de naturaleza: *negativa* = sólo puede quitar; *positiva* = sólo puede sumar;
*mixta* = su sub-score puede quedar por encima o por debajo del neutro; *contexto* = entra
en denominadores y en la confianza pero no tiene peso; *restricción* = no da puntos, cambia
el estado.

## 3–5. Indicador, fórmula y comportamiento de cada variable

Notación: `hoy` = fecha de corte; ventana de tasas = `ventana_tasas_dias` (90 d por
defecto); los eventos se miran sobre `ventana_eventos_dias` (730 d) con semivida.

### 3.1 Variables de evento (suspensión piloto, suspensión pasajero, invitaciones Pibox/Rent, expulsión, baneo IMEI, conducta inapropiada)

- **A. Qué mide:** cuánto pesa *hoy* el historial disciplinario de ese tipo, combinando
  **cantidad**, **antigüedad** y **severidad**. No se mide como tasa sobre servicios: una
  suspensión no se "diluye" por hacer más viajes (eso sería manipulable con volumen).
- **B. Entrada:** lista de eventos `(fecha, activo, severidad opcional)` por piloto.
- **C. Indicador — carga con decaimiento de semivida:**
  ```
  carga_v = Σ_i  severidad_i · 0.5^( (hoy − fecha_i) / semivida_v )      sólo eventos con edad ≤ ventana_eventos
  ```
  Justificación de la lógica temporal: la semivida es el único parámetro y tiene lectura
  directa ("a los 180 días una suspensión pesa la mitad; al año, un cuarto"). Es
  monótona, acumulativa (dos eventos recientes pesan ~2) y auditable: cada evento aporta
  un número que se puede listar. Se descartó una ventana dura ("cuenta si es de los
  últimos 6 meses") porque produce saltos: el día 181 la suspensión desaparece.
- **D. Normalización:** `sub_v = 5 · (1 − min(1, carga_v / tope_v))`. El `tope` es la carga a
  la que la variable llega a 0 (p. ej. `tope = 2` = "dos eventos de hoy" o "cuatro de hace
  una semivida").
- **E. Impacto positivo:** nunca suma. Sin eventos → sub = 5 → descuento 0.
- **F. Impacto negativo:** cualquier evento dentro de la ventana; más reciente, más severo
  o más repetido → mayor descuento.
- **G. Sin impacto:** eventos más viejos que `ventana_eventos_dias`; tipos no aplicables al
  servicio (p. ej. IMEI en B2B); variable con peso 0.
- **H. Sin datos:** "no hay eventos registrados" se trata como **cero eventos** (sub = 5).
  Si la *fuente entera* no está disponible (tabla caída), la variable se marca `sin_dato`
  y sale del cálculo — nunca se asume lo peor ni lo mejor.
- **I. Extremos:** el `tope` satura (10 suspensiones no valen más que 3); el peso relativo
  dentro del bloque acota el descuento máximo de cada variable a `α · w_v / Σw_eventos`.
- **J. A 0–5:** el sub-score ya está en 0–5; entra al bloque de antecedentes como
  `1 − sub/5` (fracción de penalización).
- **Evento activo** (suspensión vigente, expulsado hoy, IMEI baneado hoy, bloqueo 24 h en
  curso): además del descuento, si `activo_restringe = true` el estado pasa a
  **RESTRINGIDO**. Eso es una restricción, no puntos.

#### 3.1.1 Conducta inapropiada confirmada (`conducta_inapropiada`) — agregada 2026-09-15

Acoso / hostigamiento del piloto hacia el pasajero, según el módulo **Conducta
Inapropiada** del portal (chats clasificados por IA y revisados por un analista).

- **Fuente:** `picapmongoprod.dashboard_conducta_listas` (una fila por servicio alertado).
  Entran **sólo** los casos con `sujeto_rol = 'Piloto'` y `novedad = 'con_novedad'`: la
  grosería o el acoso ya fue **confirmado** por quien revisó. Un caso que el batch alertó
  pero nadie marcó (`sin_revisar`) o que se marcó "Sin Novedad" **no descuenta nada**.
- **Un evento por (piloto, día del caso)**, con fecha = `run_date`, desde que arrancó la
  revisión (histórico completo). `subtipo` = clasificación (`ABUSIVE_LANGUAGE` lenguaje
  abusivo / `PROSTITUTION_FRAUD` acoso sexual) con severidad configurable por subtipo
  (hoy 1.0 las dos; a definir con Riesgo).
- **Misma fórmula que el resto de antecedentes** (§3.1): carga con semivida 180 d y
  **tope 5** — deliberadamente alto para que sea *moderado*: un caso de hoy carga 0.2 de
  5 (sub-score 4.0), hacen falta cinco casos recientes para llevar la variable a 0. Con
  peso 8 en los tres tipos, un piloto de 4.9 pasa a **4.7 con un caso, 4.4 con tres, 4.1
  con cinco**, y a 4.8 si el caso es de hace seis meses.
- Aplica a **B2B, RENT y B2C** por igual. No restringe (`activo_restringe: false`): la
  suspensión o expulsión que decida Operaciones llega por su propia variable.
- **Doble penalización:** la alerta del portal por pico de chats marcados
  (`conducta_inapropiada_spike`) queda en `reglas.yaml` como `alerta` con
  `mide_score: conducta_inapropiada`, así la misma conducta no resta dos veces.
- Extracción: `sql/06_conducta.sql` → `data_real/eventos_conducta.csv`.

### 3.2 Cancelación propia (`cancelacion_piloto`)

- **A.** Propensión del piloto a abandonar servicios **que dependían de él**.
- **B.** Conteos en la ventana: `finalizados`, `cancel_piloto`, `cancel_pasajero`,
  `cancel_plataforma`, `otros_atribuibles` (no-show, abandono).
  En Rent, con `bookings.status_cd`: 100 = canceló el piloto, 102 = canceló el usuario,
  104 = plataforma, 101 = expiró sin piloto (no cuenta), 4/107/108 = finalizado.
- **C.** `n_aplicables = finalizados + cancel_piloto + otros_atribuibles`
  (servicios cuyo desenlace dependió del piloto). **Las cancelaciones del pasajero y de
  la plataforma no entran ni al numerador ni al denominador**: no son conducta del piloto
  y, si se dejaran en el denominador, diluirían su tasa.
  ```
  tasa_cruda    = cancel_piloto / n_aplicables
  tasa_ajustada = (cancel_piloto + m·p₀) / (n_aplicables + m)
  ```
- **D.** `sub = rampa(tasa_ajustada, x₀ = 0.30, x₅ = 0.03)` (menos es mejor).
- **E/F.** Sube al bajar la tasa; baja al subir. Neutro ≈ `rampa(p₀)`.
- **G.** Sin efecto si `n_aplicables = 0` (`sin_dato`, sale del cálculo).
- **H.** Conteo nulo = 0 servicios, no "dato faltante"; si la fuente no existe, `sin_dato`.
- **I.** Suavizado: con `m = 10` y `p₀ = 8 %`, 1 cancelación en 3 servicios no se lee como
  33 % sino como `(1 + 0.8)/13 = 13.8 %`. La rampa además recorta por arriba.
- **J.** `rampa` → 0–5.

### 3.3 Tasa de finalización y `finalizados`

`tasa_finalización = finalizados / n_aplicables`. Con las categorías actuales (finalizado ∨
cancelado por piloto ∨ otros atribuibles) es **algebraicamente `1 − tasa_cancelación`**
cuando `otros_atribuibles = 0`: darle peso a ambas contaría la misma conducta dos veces.
Se calcula y se muestra como métrica de contexto (`detalle.tasa_finalizacion`), pero **la
variable puntuada `finalizados` mide experiencia/volumen**:

```
sub_finalizados = 5 · min(1, ln(1 + finalizados) / ln(1 + n_ref[tipo]))
```

- Positiva y saturante: el primer tramo vale mucho (0 → 20 servicios ya da ~3.0 con
  n_ref = 150), después de `n_ref` no suma más — no premia volumen infinito.
- Sin efecto si `n_aplicables = 0` (`sin_dato`). Si Operaciones aporta una categoría
  atribuible distinta de la cancelación (p. ej. "no se presentó"), la tasa de finalización
  deja de ser redundante y puede recibir peso propio: el motor ya la calcula.

### 3.4 Sin novedades dentro de los tiempos (`sin_novedades`, B2B y B2C)

- **A.** Consistencia del buen desempeño: fracción de los servicios finalizados que
  cerraron sin novedad **y** dentro del tiempo.
- **B.** `finalizados`, `ok = finalizados sin novedad y a tiempo` (ventana).
- **C.** `tasa_ajustada = (ok + m·p₀)/(finalizados + m)`, `p₀ = 0.90`, `m = 10`.
- **D.** `sub = rampa(tasa_ajustada, x₀ = 0.60, x₅ = 0.97)`.
- **E/F/G.** Sube por encima de p₀, baja por debajo; sin efecto con 0 finalizados.
- **I.** 3 servicios perfectos dan `(3 + 9)/13 = 92 %` → 4.4, no 5.0: **no hay beneficio
  exagerado por pocos servicios limpios**; hace falta acumular.

### 3.5 Valor declarado mayor (`alto_valor`, B2B y B2C)

- **A.** Responsabilidad *demostrada* en servicios de alto valor — no "hace servicios caros".
- **B.** `n_av` = finalizados con `valor_declarado ≥ umbral[tipo]`; `ok_av` = de esos, los
  sin novedad y a tiempo; `finalizados` totales.
- **C.** Dos componentes que se multiplican:
  ```
  exposición   = √( min(1, n_av / n_ref) · min(1, (n_av / finalizados) / prop_ref) )   ∈ [0,1]
  cumplimiento = (ok_av + m·p₀) / (n_av + m)
  sub = s_neutro + exposición · ( rampa(cumplimiento) − s_neutro ),   s_neutro = rampa(p₀)
  ```
  La exposición combina **cantidad** y **proporción** (media geométrica: hace falta las
  dos; 5 de 500 servicios no es exposición aunque 5 ≥ n_ref/2). El sub-score parte del
  **neutro** (lo que obtendría un piloto promedio) y se aleja de él sólo en la medida de
  la exposición: poca exposición ≈ neutro, mucha exposición y buen cumplimiento → hasta 5,
  mucha exposición y mal cumplimiento → hacia 0. Eso cumple las cinco condiciones del
  requerimiento (cantidad, proporción, cumplimiento, ausencia de novedades, volumen).
- **G.** `n_av = 0` → `sin_dato` (sale del cálculo: no se penaliza a quien no recibe esos
  servicios).
- **I.** Cumplimiento suavizado + exposición acotada a 1.

### 3.6 Cumplimiento de reservas (`cumplimiento_reservas`, B2B)

- **B.** Por reserva: cumplida / incumplida atribuible / cancelada atribuible / **no
  atribuible** (causa externa o justificada).
- **C.** `n = cumplidas + incumplidas_atrib + canceladas_atrib` — **las no atribuibles se
  excluyen del denominador** (no se penalizan, tampoco se premian).
  `tasa_ajustada = (cumplidas + m·p₀)/(n + m)`, `p₀ = 0.90`, `m = 5`.
- **D.** `sub = rampa(tasa_ajustada, 0.60, 0.97)`. **G.** `n = 0` → `sin_dato`.

### 3.7 Recaudo pagado en ≤ 24 h hábiles (`recaudo_24h`, B2B) — "24 hrs a excepción de un FDS"

- **A.** Cuando el piloto recaudó contra entrega y **no abonó en el momento**, ¿pagó dentro
  del plazo? Mide disciplina con la plata del cliente, no cuántos recaudos hace.
- **B.** Por episodio: `fecha_recaudo` (la transacción negativa
  `WalletAccountCounterDeliveryTransaction` con `package_id`) y `fecha_abono` (la positiva
  que la cierra) o vacío si sigue sin pagar. Ventana de 90 días.
- **C.** Horas **hábiles** entre recaudo y abono: se cuentan sólo lunes a viernes
  (`horas_habiles`; un recaudo del viernes 17:00 pagado el lunes 15:00 lleva 22 h, a
  tiempo). Cada episodio queda en una de cuatro cajas:
  `a_tiempo` (h ≤ 24) · `tarde` (pagado con h > 24) · `vencido_sin_pagar` (sin abono y
  h > 24) · `pendiente_en_plazo` (sin abono, h ≤ 24 — **no cuenta**, todavía puede pagar).
  ```
  n = a_tiempo + tarde + vencidos
  tasa_ajustada = (a_tiempo + m·p₀) / (n + m),   p₀ = 0.85, m = 5
  ```
- **D.** `sub = rampa(tasa_ajustada, x₀ = 0.40, x₅ = 0.95)`.
- **E/F.** Sube si paga a tiempo; baja si paga tarde o no paga. Un **vencido sin pagar**
  cuenta como "no a tiempo" **y** dispara la alerta `recaudo_pendiente` (capa 2), que se
  ve en observaciones. Si Operaciones decide que debe bloquear, es un cambio en
  `reglas.yaml`, no en la fórmula.
- **G.** Sin episodios → `sin_dato` (no se premia ni castiga a quien nunca dejó recaudo
  pendiente). No aplica en Rent ni B2C.
- **I.** Suavizado + rampa; los pendientes en plazo no entran.
- SQL: horas hábiles = `dateDiff('hour', a, b) − 48 · (semanas completas) − horas de
  sábado/domingo del tramo`; más simple y equivalente: sumar por día con
  `arrayJoin(range(...))` y `toDayOfWeek(d) <= 5`. En Excel: `=NETWORKDAYS`-style con
  `DÍAS.LAB` para días enteros + horas de los extremos.

### 3.8 Servicios totales por tipo (contexto)

No puntúa. Alimenta `n_aplicables` (denominadores y **confianza**) y permite calcular la
proporción de alto valor. Tratarlo como variable puntuada duplicaría `finalizados`.

## 6. Tratamiento de datos faltantes

| Situación | Tratamiento | Motivo |
|---|---|---|
| Variable **no aplica** al tipo | `motivo = no_aplica`, sale del cálculo, pesos renormalizados | Requerimiento §12: no es cero |
| Fuente disponible pero **cero registros** (0 eventos, 0 cancelaciones) | Es un **cero real** | Ausencia de evento es información |
| Denominador cero (0 finalizados, 0 reservas, 0 alto valor) | `motivo = sin_dato`, sale del cálculo | No hay evidencia que evaluar |
| Fuente **no disponible** (tabla caída, campo nunca poblado) | `sin_dato` en esa variable | Nunca asumir lo peor ni lo mejor |
| Ninguna variable de desempeño con dato (0 servicios) | `score = null`, estado `SIN_SCORE` | Sin desempeño no hay sobre qué descontar antecedentes |

La renormalización: `D = Σ w·s / Σ w` **sólo sobre las variables con score**. Un piloto B2B
sin reservas se evalúa con el resto de variables a peso proporcional.

## 7. Muestras pequeñas

Dos mecanismos, cada uno con una función distinta (no se duplican):

1. **Suavizado bayesiano en cada tasa** (`m` pseudo-observaciones al valor de referencia
   `p₀`). Es el estimador de la media de una Beta-Binomial con prior `Beta(m·p₀, m·(1−p₀))`:
   explicable como "el piloto arranca con `m` servicios ficticios al promedio de la
   población y sus propios servicios van pesando cada vez más". Con `n = m` su dato pesa
   lo mismo que la referencia; con `n ≫ m` domina su dato.
2. **Vigencia y confianza** sobre el score total: `confianza = min(1, n_aplicables / n_min)`.
   Debajo de `n_min` el score se publica como **PROVISIONAL**; a partir de `n_min`,
   **DEFINITIVO**. No se vuelve a encoger el score (ya lo hizo el paso 1): sólo se etiqueta.

## 8. Normalización a 0.0–5.0

Cada sub-score está en `[0, 5]` por construcción (`rampa` recorta; `1 − min(1, carga/tope)`
está en `[0, 1]`; la saturación logarítmica está en `[0, 1]`; el sub-score de alto valor es
una combinación convexa de dos valores en `[0, 5]`). El promedio ponderado de valores en
`[0, 5]` está en `[0, 5]`; el factor `1 − α·P` está en `[0, 1]` porque `P ∈ [0, 1]` y
`α ∈ [0, 1]`. Por lo tanto **`0 ≤ score ≤ 5` sin necesidad de recortar al final**; el motor
además lo verifica (`tests/test_engine.py::test_rango_0_5_extremos` fuerza el peor y el mejor
caso y obtiene exactamente 0.0 y 5.0). Se redondea a 1 decimal sólo al publicar.

**Bandas** (parámetro `bandas`): con un promedio ponderado el 5.0 exacto es casi
inalcanzable, así que en vez de "5.0 = excelente / 4.0–4.9 = bueno" se propone
`EXCELENTE ≥ 4.5 · BUENO ≥ 3.5 · ACEPTABLE ≥ 2.5 · DEFICIENTE ≥ 1.5 · CRÍTICO ≥ 0.5 ·
EXTREMADAMENTE CRÍTICO < 0.5`. Son parámetros; la propuesta original se puede restaurar
cambiando `desde`.

## 9. Fórmula del score final

```
D  = Σ_{v ∈ desempeño, con dato}  w_v · sub_v   /   Σ w_v                       ∈ [0, 5]
P  = Σ_{e ∈ antecedentes, aplicables}  w_e · (1 − sub_e / 5)   /   Σ w_e         ∈ [0, 1]
score_comportamental = D · (1 − α · P)                                          ∈ [0, 5]

score_final = min(score_comportamental, tope_regla)   si alguna regla activa tiene efecto "tope"
estado      = BLOQUEADO  si alguna regla activa tiene efecto "bloqueo"
            = RESTRINGIDO si hay un evento activo con activo_restringe
            = OK          en otro caso
```

- `α` (`alpha_antecedentes`, por defecto 1.0): intensidad máxima del historial. Con `α = 1`
  un historial "todo al tope" deja el score en 0; con `α = 0.5` como mucho lo reduce a la
  mitad.
- **Ninguna variable domina**: un evento sólo puede descontar hasta `α · w_e / Σ w_e` del
  score; una variable de desempeño sólo puede mover `D` en `w_v / Σ w_v · 5`. Además
  `max_participacion_peso` (35 %) se valida al cargar los pesos.
- **Desglose auditable**: cada resultado trae `contribuciones` con el peso efectivo y el
  aporte (desempeño) o descuento (antecedentes) de cada variable, y `sub_scores.detalle`
  con los números crudos (x, n, tasa cruda, tasa ajustada, carga, edades…).

## 10. Parámetros de pesos configurables

`config/pesos.yaml`, un bloque por tipo. Los nombres son exactamente las variables del motor:

```yaml
B2B:  { peso_suspension_piloto: X, peso_suspension_pasajero: X, peso_invitacion_pibox: X,
        peso_invitacion_rent: X, peso_expulsion: X, peso_recaudo_24h: X,
        peso_cancelacion_piloto: X, peso_finalizados: X, peso_alto_valor: X,
        peso_sin_novedades: X, peso_cumplimiento_reservas: X }
RENT: { …, peso_baneo_imei: X, … }        # sin alto_valor / sin_novedades / reservas / recaudo
B2C:  { … }                               # sin baneo_imei / reservas / recaudo
```

(En el YAML real las claves van sin el prefijo `peso_`.) Los pesos de **desempeño** son
relativos entre sí y los de **antecedentes** relativos entre sí; la escala absoluta no
importa (se renormalizan), sólo la proporción. Cambiarlos no cambia ninguna medición.

Los demás parámetros (semividas, topes, `p₀`, `m`, rampas, `n_ref`, `n_min`, `α`, bandas,
umbral de alto valor) están en `config/parametros.yaml`, comentados uno a uno.

## 11. Propuesta preliminar de pesos (separada de la metodología)

Es un punto de partida para discutir con Operaciones/Riesgo, **no una recomendación
validada con datos**. Está en `config/pesos.yaml` y se puede mover con el afinador
(`python3 -m score.web`).

| Variable | B2B | RENT | B2C | Lectura |
|---|---:|---:|---:|---|
| suspension_piloto | 15 | 18 | 15 | El antecedente más relevante en los tres |
| suspension_pasajero | 5 | 7 | 6 | Menor: otro rol |
| invitacion_pibox | 8 | 3 | 10 | Pesa donde el piloto opera Pibox |
| invitacion_rent | 2 | 10 | 3 | Pesa en Rent |
| expulsion | 10 | 12 | 12 | Histórica (la activa restringe) |
| baneo_imei | – | 10 | – | Sólo Rent (la activa restringe) |
| conducta_inapropiada | 8 | 8 | 8 | Casos "Con Novedad" del módulo Conducta Inapropiada; moderado (tope 5) |
| recaudo_24h | 8 | – | – | Sólo B2B: recaudo pagado en 24 h hábiles |
| cancelacion_piloto | 15 | 25 | 18 | En Rent es la conducta operativa central |
| finalizados | 7 | 15 | 10 | Experiencia |
| alto_valor | 10 | – | 12 | |
| sin_novedades | 12 | – | 14 | |
| cumplimiento_reservas | 8 | – | – | |
| **Σ desempeño / Σ antecedentes** | 52 / 56 | 40 / 68 | 54 / 54 | |

Calibración sugerida antes de fijarlos: correr el motor sobre la población real de 90
días, mirar la distribución de cada sub-score (que no esté todo pegado a 5 ni a 0), fijar
`p₀` en la mediana poblacional de cada tasa y los umbrales de rampa en percentiles
(p. ej. `x₅` = p20, `x₀` = p95 para cancelación), y revisar con Operaciones 20–30 pilotos
conocidos: los que ellos consideran ejemplares deben quedar arriba y los problemáticos
abajo. Si no, mover pesos — no fórmulas.

## 12. Ejemplos numéricos (12 casos ficticios con nombre, corte 2026-09-15)

Generados con `python3 docs/generar_ejemplos.py` sobre `data/*.csv` (D = desempeño,
P = penalización de antecedentes). `data/` trae además 120 pilotos ficticios sin nombre de
caso (`data/generar_datos_ficticios.py`) para que el ranking top/medio/peores se llene:

| Piloto | Tipo | Caso | D | P | Score | Final | Banda | Vigencia | Estado | Observaciones |
|---|---|---|---:|---:|---:|---:|---|---|---|---|
| P001 | B2B | buen comportamiento sostenido | 4.8 | 0% | 4.8 | **4.8** | EXCELENTE | DEFINITIVO (1.0) | OK | — |
| P002 | RENT | piloto nuevo, pocos servicios | 3.4 | 0% | 3.4 | **3.4** | ACEPTABLE | PROVISIONAL (0.35) | OK | Piloto con pocos servicios en la ventana: 7 de 20 necesarios (score provisional) |
| P003 | RENT | suspensión antigua + muchas finalizaciones | 5.0 | 1% | 4.9 | **4.9** | EXCELENTE | DEFINITIVO (1.0) | OK | Suspensión como piloto hace 603 días |
| P004 | B2C | comportamiento negativo reciente | 3.4 | 19% | 2.8 | **2.8** | ACEPTABLE | DEFINITIVO (1.0) | OK | Suspensión como piloto hace 10 días; Invitación Pibox hace 20 días; Conducta inapropiada confirmada hace 82 días; Novedades frecuentes: sólo 30 de 40 sin novedad y a tiempo (75%); Novedades en servicios de alto valor: 5 de 8 bien |
| P005 | B2B | alto valor con muchas novedades | 3.3 | 0% | 3.3 | **3.3** | ACEPTABLE | DEFINITIVO (1.0) | OK | Novedades frecuentes: sólo 70 de 90 sin novedad y a tiempo (78%); Novedades en servicios de alto valor: 28 de 40 bien; Incumple reservas: 4 de 14 |
| P006 | RENT | múltiples suspensiones + IMEI baneado | 4.9 | 41% | 2.9 | **2.9** | ACEPTABLE | DEFINITIVO (1.0) | BLOQUEADO [baneo_imei] ⚠ imei_compartido | Baneo de IMEI VIGENTE; 3 suspensiones como piloto (última hace 30 días); Baneo de IMEI hace 14 días; Regla activa: imei_compartido |
| P007 | B2C | cero servicios | — | — | — | **—** | SIN SCORE | SIN_SCORE (0.0) | SIN_SCORE | — |
| P008 | B2B | expulsión histórica (reintegrado) | 4.3 | 10% | 3.8 | **3.8** | BUENO | DEFINITIVO (1.0) | OK ⚠ cancelaciones_en_racha | Expulsión hace 400 días; Regla activa: cancelaciones_en_racha |
| P009 | RENT | una sola cancelación | 4.8 | 0% | 4.8 | **4.8** | EXCELENTE | DEFINITIVO (1.0) | OK | — |
| P010 | B2C | muchos servicios de alto valor bien atendidos | 5.0 | 0% | 5.0 | **5.0** | EXCELENTE | DEFINITIVO (1.0) | OK | — |
| P011 | B2B | cuenta nueva con tope por regla | 4.4 | 3% | 4.3 | **2.5** | ACEPTABLE | DEFINITIVO (1.0) | OK ⚠ cuenta_nueva_retiro_alto | Suspensión como pasajero hace 76 días; Regla activa: cuenta_nueva_retiro_alto |
| P012 | B2B | recaudos pagados tarde y uno vencido | 4.3 | 0% | 4.3 | **4.3** | BUENO | DEFINITIVO (1.0) | OK ⚠ recaudo_pendiente (1 vencido/s sin pagar) | Recaudo vencido sin pagar (1); Recaudos pagados después de 24 h: 2 de 4 |

Lectura caso por caso (§12 del requerimiento):

- **Pocos servicios** (P002, 7 servicios): score PROVISIONAL, confianza 0.35. Su
  cancelación cruda es 1/7 = 14 % pero la ajustada es `(1 + 0.8)/17 = 10.6 %`.
- **Cero servicios** (P007): sin score, estado `SIN_SCORE`. No es 0.0 ni 5.0.
- **Sin datos históricos**: cada variable sin fuente sale del cálculo (§6).
- **Suspensión antigua** (P003, hace 600 d con semivida 180): carga 0.1 → descuento 1 %.
- **Múltiples suspensiones** (P006, a 30/90/200 d): carga 2.06 ≥ tope 2 → sub 0, pero el
  descuento se limita a su participación (18/60 del bloque) → P = 46 %, no 100 %.
- **Una sola cancelación** (P009, 1/101): 4.8, prácticamente sin efecto.
- **Muchas cancelaciones** (P006, 20/142 = 14 %): sub 2.7 en la variable de más peso en Rent.
- **Muchas finalizaciones** (P003, 400): `finalizados` satura en 5; no sigue sumando.
- **Alto valor bien atendido** (P010, 59/60): alto_valor 4.9 → 5.0 total.
- **Alto valor con novedades** (P005, 28/40): alto_valor 1.65 y baja a ACEPTABLE aunque
  no tenga antecedentes — ver desglose abajo.
- **Buen comportamiento sostenido** (P001): 4.9 EXCELENTE.
- **Negativo reciente** (P004): suspensión hace 10 d + invitación + 18 % cancelación → 2.1.
- **Variable no aplicable**: en P006 (RENT) `alto_valor`, `sin_novedades`, `reservas` y
  `recaudo_24h` figuran como `no_aplica` y no pesan.
- **Recaudo tarde / vencido** (P012): 1 a tiempo (viernes → lunes, 22 h hábiles), 2 tarde
  y 1 vencido sin pagar → sub 1.8 + alerta `recaudo_pendiente`.

## 13. Ejemplo B2B (P005 — alto valor con novedades, sin antecedentes)
**P005 · Elena Quintero (alto valor con muchas novedades) · B2B** — D = 3.319, P = 0.000, factor = 1 − 1.0·P = 1.000, score = 3.32 → **3.3** (ACEPTABLE, DEFINITIVO, estado OK)

| Variable | Bloque | Sub-score | Peso efectivo | Aporte / descuento | Cálculo |
|---|---|---:|---:|---:|---|
| suspension_piloto | antecedentes | 5.00 | 31.2% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=2.0 |
| suspension_pasajero | antecedentes | 5.00 | 10.4% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=3.0 |
| invitacion_pibox | antecedentes | 5.00 | 16.7% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0 |
| invitacion_rent | antecedentes | 5.00 | 4.2% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0 |
| expulsion | antecedentes | 5.00 | 20.8% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=1.0 |
| baneo_imei | — | — | — | — | *no_aplica* |
| conducta_inapropiada | antecedentes | 5.00 | 16.7% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=5.0 |
| cancelacion_piloto | desempeno | 5.00 | 28.8% | +1.44 | x=2, n=92, tasa_cruda=0.0217, tasa_ajustada=0.0539, excluidos_no_atribuibles=6 |
| finalizados | desempeno | 4.66 | 13.5% | +0.63 | n=90, n_ref=125, tasa_finalizacion=0.9783 |
| sin_novedades | desempeno | 2.57 | 23.1% | +0.59 | x=70, n=90, tasa_cruda=0.7778, tasa_ajustada=0.79 |
| alto_valor | desempeno | 1.65 | 19.2% | +0.32 | n_alto_valor=40, ok=28, proporcion=0.4444, exposicion=1.0, cumplimiento_ajustado=0.7222, score_neutro=4.054, score_desempeno=1.652 |
| recaudo_24h | — | — | — | — | *sin_dato* |
| cumplimiento_reservas | desempeno | 2.21 | 15.4% | +0.34 | cumplidas=10, incumplidas_atrib=4, n=14, no_atribuibles_excluidas=1, tasa_cruda=0.7143, tasa_ajustada=0.7632 |

Cómo se lee: D = 3.32 (cancelación propia 2 % → 5, experiencia 4.5, pero sin novedades 2.6,
alto valor 1.65 y reservas 2.2); sin antecedentes P = 0 → score 3.3 ACEPTABLE. En el modelo
aditivo original este mismo piloto daba 4.1 BUENO.

## 14. Ejemplo Rent (P006 — múltiples suspensiones, IMEI baneado, regla de bloqueo)
**P006 · Fabián Ospina (múltiples suspensiones + IMEI baneado) · RENT** — D = 4.874, P = 0.408, factor = 1 − 1.0·P = 0.592, score = 2.89 → **2.9** (ACEPTABLE, DEFINITIVO, estado BLOQUEADO)

| Variable | Bloque | Sub-score | Peso efectivo | Aporte / descuento | Cálculo |
|---|---|---:|---:|---:|---|
| suspension_piloto | antecedentes | 0.00 | 26.5% | −26.5% | n_eventos=3, en_ventana=3, carga=2.061, tope=2.0 |
| suspension_pasajero | antecedentes | 5.00 | 10.3% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=3.0 |
| invitacion_pibox | antecedentes | 5.00 | 4.4% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0 |
| invitacion_rent | antecedentes | 5.00 | 14.7% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0 |
| expulsion | antecedentes | 5.00 | 17.6% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=1.0 |
| baneo_imei | antecedentes | 0.13 | 14.7% | −14.3% | n_eventos=1, en_ventana=1, carga=0.974, tope=1.0 |
| conducta_inapropiada | antecedentes | 5.00 | 11.8% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=5.0 |
| cancelacion_piloto | desempeno | 5.00 | 62.5% | +3.12 | x=20, n=142, tasa_cruda=0.1408, tasa_ajustada=0.1539, excluidos_no_atribuibles=16 |
| finalizados | desempeno | 4.66 | 37.5% | +1.75 | n=120, n_ref=170, tasa_finalizacion=0.8451 |
| sin_novedades | — | — | — | — | *no_aplica* |
| alto_valor | — | — | — | — | *no_aplica* |
| recaudo_24h | — | — | — | — | *no_aplica* |
| cumplimiento_reservas | — | — | — | — | *no_aplica* |

Cómo se lee: D = 4.87 (cancelación 14 %, que tras la calibración con datos reales queda
por debajo de la mediana de Rent, y experiencia alta); P = 0.265·1.0 (suspensiones al
tope) + 0.147·0.97 (IMEI reciente) = 0.41 → score 4.87 · 0.59 = 2.9 ACEPTABLE. Además el
IMEI activo lo deja RESTRINGIDO y la regla `imei_compartido` lo deja **BLOQUEADO**: el
score se calcula y se muestra, pero no habilita nada.

## 15. Ejemplo B2C (P004 — comportamiento negativo reciente)
**P004 · Diego Salazar (comportamiento negativo reciente) · B2C** — D = 3.429, P = 0.195, factor = 1 − 1.0·P = 0.805, score = 2.76 → **2.8** (ACEPTABLE, DEFINITIVO, estado OK)

| Variable | Bloque | Sub-score | Peso efectivo | Aporte / descuento | Cálculo |
|---|---|---:|---:|---:|---|
| suspension_piloto | antecedentes | 2.59 | 27.8% | −13.4% | n_eventos=1, en_ventana=1, carga=0.962, tope=2.0 |
| suspension_pasajero | antecedentes | 5.00 | 11.1% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=3.0 |
| invitacion_pibox | antecedentes | 3.93 | 18.5% | −4.0% | n_eventos=1, en_ventana=1, carga=0.857, tope=4.0 |
| invitacion_rent | antecedentes | 5.00 | 5.6% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0 |
| expulsion | antecedentes | 5.00 | 22.2% | −0.0% | n_eventos=0, en_ventana=0, carga=0.0, tope=1.0 |
| baneo_imei | — | — | — | — | *no_aplica* |
| conducta_inapropiada | antecedentes | 4.27 | 14.8% | −2.2% | n_eventos=1, en_ventana=1, carga=0.729, tope=5.0 |
| cancelacion_piloto | desempeno | 5.00 | 33.3% | +1.67 | x=9, n=50, tasa_cruda=0.18, tasa_ajustada=0.22, excluidos_no_atribuibles=5 |
| finalizados | desempeno | 3.70 | 18.5% | +0.69 | n=40, n_ref=150, tasa_finalizacion=0.8 |
| sin_novedades | desempeno | 2.43 | 25.9% | +0.63 | x=30, n=40, tasa_cruda=0.75, tasa_ajustada=0.78 |
| alto_valor | desempeno | 2.01 | 22.2% | +0.45 | n_alto_valor=8, ok=5, proporcion=0.2, exposicion=0.8944, cumplimiento_ajustado=0.7308, score_neutro=4.054, score_desempeno=1.767 |
| recaudo_24h | — | — | — | — | *no_aplica* |
| cumplimiento_reservas | — | — | — | — | *no_aplica* |

Cómo se lee: D = 3.43 (su 18 % de cancelación queda bien parado frente a la mediana real
de B2C, 42 %; lo que lo baja son las novedades). La suspensión de hace 10 días pesa 0.96
de carga (tope 2 → sub 2.59) y descuenta 13,4 %; la invitación de hace 20 días 4,0 %; y
el caso de **conducta inapropiada confirmado hace 82 días** carga 0.73 de 5 (sub 4.27) y
descuenta 2,2 % → factor 0.80 → 2.8 ACEPTABLE. Dentro de 6 meses, sin nuevos eventos, la
suspensión pesará 0.5 y el descuento total bajará a ~10 %.

## 16. Implementación en SQL / Python / Power BI

**Contexto que acompaña al score** (no puntúa, se muestra en el ranking): `driver_id`,
`passenger_id`, nombre real (`passengers`), fecha de activación como piloto y como
pasajero, calificación del **gamification** (BD ClickHouse existente — tabla por ubicar)
y calificación en la **app**. Las **observaciones** (piloto nuevo, cancelación alta,
suspensión hace N días, recaudo vencido…) las genera el motor a partir de los sub-scores,
no se escriben a mano. El ranking se presenta como **top 10 mejores / 10 del medio / 10
peores** por tipo.

**Capas de datos** (una tabla por capa, todas por `piloto_id × tipo × fecha_corte`):

1. `agg_servicios`: conteos de la ventana (`finalizados`, `cancel_piloto`, `cancel_pasajero`,
   `cancel_plataforma`, `otros_atribuibles`, `ok_sin_novedad`, `n_alto_valor`,
   `ok_alto_valor`, reservas por categoría). En ClickHouse, sobre `bookings` con
   `status_cd` (100/102/104/101/4-107-108) y `driver_id`; `sql/extraccion_clickhouse.sql`
   trae el esqueleto. Recaudos: pares recaudo/abono de
   `wallet_account_transactions` con `_type = 'WalletAccountCounterDeliveryTransaction'`
   (quedarse con la pata que trae `package_id`; el lote de compensación viene sin él).
2. `eventos`: una fila por evento `(piloto_id, tipo_evento, fecha, activo)`. Suspensiones y
   expulsiones salen de `passengers.is_driver_suspended / suspended / expelled` y de
   `passenger_suspensions`; IMEI de `sessions.imei/active`. Invitaciones y 24 h: fuente por
   confirmar.
3. `reglas_activas`: `(piloto_id, regla)` del motor de reglas que ya existe.
4. `score`: salida del motor, con el desglose en columnas (un sub-score y un aporte por
   variable) para que Power BI lo muestre sin recalcular nada.

**Traducción de las primitivas:**

| Primitiva | SQL (ClickHouse) | Excel / DAX |
|---|---|---|
| rampa | `5 * least(1, greatest(0, (x - x0) / (x5 - x0)))` | `=5*MIN(1,MAX(0,(x-x0)/(x5-x0)))` |
| tasa_ajustada | `(x + m * p0) / (n + m)` | `=(x+m*p0)/(n+m)` |
| decaimiento | `pow(0.5, dateDiff('day', fecha, hoy) / semivida)` | `=0.5^((hoy-fecha)/semivida)` |
| carga | `sum(severidad * pow(0.5, edad / semivida))` con `GROUP BY piloto_id, tipo_evento` | SUMPRODUCT sobre la lista de eventos |
| saturación | `5 * least(1, log1p(n) / log1p(n_ref))` | `=5*MIN(1,LN(1+n)/LN(1+n_ref))` |
| D | `sum(w * s) / sum(w)` sobre filas con `s IS NOT NULL` | SUMPRODUCT / SUMIFS excluyendo vacíos |

Recomendación: **materializar los sub-scores** (una columna por variable) y no sólo el
score final; el desglose es lo que hace auditable y explicable el número. Los parámetros
van en una tabla `parametros(tipo, variable, nombre, valor)` que Power BI y SQL leen — no
hard-codeados en la query. Recalcular diariamente por `fecha_corte` y guardar el histórico
(el decaimiento hace que el score cambie aunque no pase nada nuevo).

## 17. Riesgos de diseño y formas de manipular el score

| Riesgo / manipulación | Mitigación en el modelo | Queda pendiente |
|---|---|---|
| **Inflar volumen** con servicios triviales para "diluir" cancelaciones o subir `finalizados` | Eventos no se miden como tasa (no se diluyen); `finalizados` satura en `n_ref`; la cancelación es tasa (el volumen no la baja) | Vigilar servicios muy cortos / cancelados-recreados (regla existente) |
| **Cancelar por fuera** (pedirle al pasajero que cancele) para que cuente como no atribuible | Sólo se excluye lo que el sistema marca como cancelación del pasajero/plataforma | Regla de riesgo: patrón de `status 102` con el mismo piloto en racha |
| **Muchos servicios pequeños de alto valor justo sobre el umbral** | `alto_valor` combina cantidad **y** proporción, y sólo sube con cumplimiento | Umbral por percentil, revisado periódicamente |
| **Cuenta nueva para limpiar antecedentes** | El score no lo ve; lo ve la capa de reglas (IMEI, RF) → bloqueo | Cruce de identidad (IMEI/RF) debe seguir siendo regla |
| **Doble penalización** score + regla por la misma conducta | Catálogo `reglas.yaml` con `mide_score`: si el score ya cubre la conducta, la regla es `alerta`, no `tope` | Mantener el catálogo al día |
| **Descuento perpetuo** por un evento viejo | Semivida + ventana de 730 d | Definir con Riesgo si expulsiones/IMEI deben decaer más lento |
| **Dependencia de `p₀` y umbrales mal calibrados** (todo el mundo en 5 o en 0) | Parámetros centralizados + afinador local para ver la distribución | Calibrar con población real antes de publicar |
| **Piloto nuevo sobre/infra-evaluado** | Suavizado + PROVISIONAL bajo `n_min` | Decidir si un PROVISIONAL habilita lo mismo que un DEFINITIVO |
| **Cambio silencioso de pesos** | `pesos.yaml` versionado; el desglose deja rastro de qué peso se usó | Registrar `version_parametros` junto al score histórico |
| **Datos faltantes leídos como cero** | `sin_dato` explícito y distinto de 0 | Monitorear el % de variables `sin_dato` por corte |
