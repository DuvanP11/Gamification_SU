# Score Operacional de Pilotos (0.0 – 5.0) — Metodología

> Versión 0.4 · borrador de trabajo · 2026-09-15.
> **v0.4 — "cuenta de confianza":** el score es una base que se gana con experiencia y
> antigüedad (un piloto **recién activado arranca en 0.0**), más lo que el piloto hace
> **mejor** que la referencia de su tipo, menos lo que hace **peor** y sus antecedentes. Las
> variables operativas (cancelación, sin novedades, recaudo, alto valor, reservas) son
> **mixtas**: la misma variable suma o resta según de qué lado de la referencia esté. Se
> agregan **antigüedad**, **activación express** (resta y se apaga) y **conducta
> inapropiada confirmada** (resta), y el **cupo de confianza en plata** (§18).
> Los **pesos son definitivos desde el 2026-09-16** (§11, `config/pesos.yaml`); los umbrales de
> medición (`config/parametros.yaml`) están calibrados donde hubo datos (cancelación,
> calificación) y son preliminares en el resto. La metodología
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
| Recaudo "entregado bien" / "con novedad" / "no pagó" (2026-09-16) | Sobre TODO recaudo contra entrega: **bien** = la billetera Picash del piloto volvió a ≥ 0 dentro de 24 h hábiles; **novedad** = volvió a ≥ 0 después del plazo; **no pagó** = sigue en rojo con el plazo vencido (pesa doble) → variable `recaudo_entregado` | Si "novedad" incluye además otra cosa (entrega parcial, reclamo del comercio) y de dónde sale; si el plazo es el mismo de `recaudo_24h` |
| Calificación del pasajero al piloto (2026-09-16) | `bookings.rate_to_driver` 1–5 sólo en servicios finalizados; `''` (no calificó), `'0'` (saltó la calificación) y los cincos de cancelados quedan fuera → variable `calificacion_pasajero` (Rent y B2C; calibrada con `sql/calibracion_calificacion.sql`) | Por qué en B2B la nota es 5,0 en casi todos los pilotos (¿califica el cliente o es automática?) |

---

## 1. Arquitectura general

Tres capas, cada una con una responsabilidad y **sin mezclarse**:

```
                ┌──────────────────────────────────────────────────────────────┐
 datos ──────▶  │ CAPA 1 · SCORE COMPORTAMENTAL (0–5)                          │
 (ventana +     │   BASE ganada (0→3.5) + lo que hace MEJOR que la referencia   │
  historial)    │   (hasta +1.5) − lo que hace PEOR y antecedentes (hasta −3.5)  │
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

**Por qué no es un único `Σ(score × peso)`.** Se probó primero (ver §9): un historial limpio
recibía 5.0 en las variables de eventos y diluía todo, y "cancelar poco" se leía como mérito
cuando es lo normal. El modelo v0.4 es una **cuenta de confianza** con tres tipos de variable,
exactamente como pedía el requerimiento (§10: positivas, negativas, mixtas):

- **Base (sólo suma):** experiencia (servicios finalizados) y antigüedad como piloto. Es la
  confianza que se gana con el tiempo, de 0 a `base_confianza_max` (3.5). Un piloto recién
  activado vale 0.0 y sube a medida que trabaja.
- **Mixtas (suman o restan):** servicios sin novedad, recaudo en 24 h, alto valor y
  reservas. Cada una se compara con la **referencia de su tipo** (`p₀`, la
  mediana real): mejor que la referencia **suma** (hasta +1.5 en total, y sólo en proporción
  a la evidencia acumulada); peor **resta**. Igual que la referencia = 0.
- **Negativas (sólo restan):** **cancelación propia** (cancelar como el promedio o menos
  vale 0, cancelar más resta), suspensiones, invitaciones, expulsión, IMEI, conducta
  inapropiada confirmada y activación express. Un historial limpio no suma: vale 0.

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
| Recaudo pagado en 24 h hábiles | ✓ | – | – | **Mixta** (tasa) + alerta si vencido | Comportamiento | balance vs. referencia; vencido sin pagar cuenta como tarde |
| **Recaudo entregado bien** (2026-09-16) | ✓ | – | ✓ | **Mixta** (tasa) | Comportamiento | sobre TODOS los recaudos: bien suma, con novedad o sin pagar resta (no pago pesa doble) |
| **Calificación del pasajero al piloto** (2026-09-16) | – | ✓ | ✓ | **Mixta** (promedio 1–5) | Comportamiento | promedio suavizado de `rate_to_driver` en finalizados vs. referencia poblacional (en B2B la nota es ~siempre 5: no aplica) |
| Servicios que canceló | ✓ | ✓ | ✓ | **Negativa** (tasa) | Comportamiento | resta sólo por encima de la referencia p₀ (mediana real por tipo); cancelar menos no suma |
| Servicios finalizados | ✓ | ✓ | ✓ | Positiva | Base | volumen saturante (experiencia) |
| **Antigüedad como piloto** | ✓ | ✓ | ✓ | Positiva | Base | días desde la activación, satura a `dias_ref` |
| **Activación express** (`activation_record_cd = 2`, inferido) | ✓ | ✓ | ✓ | Negativa | Comportamiento | resta y se apaga con semivida desde la activación |
| Servicios totales por tipo | ✓ | ✓ | ✓ | **Contexto** | — | denominadores + confianza (no puntúa) |
| Valor declarado mayor | ✓ | – | ✓ | **Mixta** | Comportamiento | balance de cumplimiento × exposición |
| Sin novedades en tiempos | ✓ | – | ✓ | **Mixta** (tasa) | Comportamiento | balance vs. referencia |
| Incumplimiento de reserva | ✓ | – | – | **Mixta** (tasa) | Comportamiento | balance vs. referencia (no asistidas atribuibles) |
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

### 3.7b Recaudo entregado bien (`recaudo_entregado`, B2B y B2C) — agregada 2026-09-16

- **A.** ¿Cuando tuvo que entregar un recaudo contra entrega, lo hizo bien? Entregarlo bien
  **suma**; entregarlo con novedad o no entregarlo **resta**. A diferencia de `recaudo_24h`,
  acá entran **todos** los recaudos, incluidos los que abonó en el momento (que en
  `recaudo_24h` ni siquiera son episodio): el que siempre entrega al toque gana puntos.
- **B.** Por recaudo (`sql/03_recaudos.sql`, 90 días): `fecha_recaudo` (pata negativa de
  `WalletAccountCounterDeliveryTransaction` con `package_id`), `monto` y `fecha_saldado` =
  primera transacción de la **misma billetera Picash** desde el recaudo con
  `amount_after_transaction ≥ 0` — el criterio de "saldado" del portal
  (`RecaudosDeudaService`: la billetera volvió a cero). Con CSV viejos sin esa columna se usa
  el abono del booking.
- **C.** Horas hábiles entre recaudo y saldado (`horas_habiles`, lunes a viernes). Cajas:
  `bien` (h ≤ 24) · `novedad` (saldado con h > 24) · `no_pago` (sin saldar y h > 24) ·
  `en_plazo` (sin saldar, h ≤ 24 — **no cuenta**).
  ```
  n = bien + novedad + peso_no_pago · no_pago        (peso_no_pago = 2: no pagar es peor que pagar tarde)
  tasa_ajustada = (bien + m·p₀) / (n + m),   p₀ = 0.90, m = 5
  ```
- **D.** `sub = rampa(tasa_ajustada, x₀ = 0.50, x₅ = 0.95)`; el neutro es `rampa(p₀)`.
- **E/F.** Por encima de p₀ suma, por debajo resta. Un no pago vencido deja además la
  observación "Recaudos sin entregar: k ($ monto)"; la alerta `recaudo_pendiente` la sigue
  dando `recaudo_24h`, que no cambia.
- **G.** Sin recaudos en la ventana → `sin_dato`. No aplica en Rent.
- **Solapamiento con `recaudo_24h`:** un recaudo pagado tarde resta en las dos variables.
  Se dejó así a propósito porque miden cosas distintas (`recaudo_24h` = disciplina cuando
  no abonó en el momento, la definición confirmada del "24 hrs a excepción de un FDS";
  `recaudo_entregado` = cumplimiento sobre todo lo que tuvo que entregar). Si Operaciones
  prefiere una sola, se baja el peso de la otra en `pesos.yaml`; no hace falta tocar fórmulas.
- SQL: `sql/03_recaudos.sql` (CTE `sal`).

### 3.7c Calificación del pasajero al piloto (`calificacion_pasajero`, Rent y B2C) — agregada 2026-09-16

- **A.** Qué tan bien lo califican los pasajeros en la app, medido con el dato crudo por
  servicio, **no** con `passengers.rating_as_driver__fl`: verificado el 2026-09-16 que ese
  campo NO es el promedio de lo que ponen los pasajeros (promedio real 4,85 vs 4,05 en la
  app, correlación 0,44; un piloto con 2.280 notas a 4,79 figura con 3,44).
- **B.** `n_calificados` y `suma_calificaciones` (`sql/01_pilotos.sql`, 180 días): servicios
  **finalizados** (status 4/107/108) con `rate_to_driver` en `'1'…'5'`. Quedan fuera `''`
  (el pasajero nunca llegó a calificar), `'0'` (saltó la calificación —
  `skip_rate_by_passenger = true` en el 100 %) y los cincos de servicios cancelados (~14 % de
  los cincos, parecen valor por defecto). El comentario (`rate_to_driver_comment`) viene
  vacío siempre, así que no se usa.
- **C.** Promedio suavizado hacia la referencia poblacional de su tipo (misma idea que la
  tasa ajustada, sobre una nota 1–5):
  ```
  promedio_ajustado = (Σ notas + m·p₀) / (n + m),   p₀ = mediana del tipo, m = 10
  ```
- **D.** `sub = rampa(promedio_ajustado, x₀ = p10, x₅ = p80)`; el neutro es `rampa(p₀)`.
- **E/F/G.** Por encima de la referencia suma, por debajo resta; sin notas → `sin_dato`.
- **I.** Con pocas notas el promedio se pega a la referencia: en Rent 3 cincos dan
  `(15 + 48.25)/13 = 4.87` → apenas por encima del neutro; hacen falta decenas de notas para
  ganar el máximo.
- **Calibración (2026-09-16, `sql/calibracion_calificacion.sql`, 180 d, pilotos con ≥ 20 notas):**

  | Tipo | Pilotos | p10 → `x₀` | p50 → `p₀` | p80 → `x₅` | p90 |
  |---|---:|---:|---:|---:|---:|
  | RENT | 6.063 | 4,606 | 4,825 | 4,911 | 4,950 |
  | B2C | 4.336 | 4,778 | 4,917 | 4,964 | 4,985 |
  | B2B | 242 | 4,981 | 5,000 | 5,000 | 5,000 |

  La escala es estrecha porque el 92 % de las notas son 5: en Rent, 4,6 de promedio ya es
  "lo peor" y 4,91 "lo mejor". **En B2B la nota no discrimina** — del p20 al p90 todos los
  pilotos están en 5,000 exacto, así que parece una calificación automática del cliente
  empresa, no una opinión. Por eso la variable **no aplica en B2B**; si algún día el cliente
  califica de verdad, se recalibra y se agrega a `aplicabilidad`.
- **Consecuencia en Rent:** es la primera mixta que aplica en Rent, así que la base de Rent
  vuelve a topar en 3,5 como en B2B/B2C (ver §9): un veterano Rent típico ya no queda en
  ~4,9 por defecto; sube hasta 5 si los pasajeros lo califican por encima de la referencia.
- SQL: ver §16.

### 3.8 Servicios totales por tipo (contexto)

No puntúa. Alimenta `n_aplicables` (denominadores y **confianza**) y permite calcular la
proporción de alto valor. Tratarlo como variable puntuada duplicaría `finalizados`.

## 5b. Manejo de tiempos (ventanas por variable)

Cada variable mira **su propia ventana**; lo que queda fuera no la afecta (parámetro
`ventana_dias` / `desde` en `parametros.yaml`, extracción con las columnas `vc_*` y `vn_*`):

| Variable | Ventana | Cómo |
|---|---|---|
| Cancelaciones propias | **últimos 6 meses** (180 d) | tasa sobre los servicios de esos 6 meses; una cancelación de hace 7 meses ya no castiga |
| Servicios sin novedad y a tiempo | **último año** (365 d) | tasa sobre los finalizados del año |
| Cumplimiento de reservas | **últimos 3 meses** (90 d) | tasa sobre las reservas de esos 3 meses |
| Conducta inapropiada confirmada | **desde el 2026-07-01** (activación de la revisión), **sin decaimiento** | todos los casos confirmados desde julio pesan igual; cuando el módulo lleve más tiempo, pasar a ventana móvil o semivida |
| Calificación del pasajero | **últimos 6 meses** (180 d) | promedio de las notas 1–5 de los finalizados de esos 6 meses |
| Experiencia (base), recaudo (las dos), alto valor | 90 d (ventana por defecto) | — |
| Suspensiones, invitaciones, expulsión, IMEI, express | 730 d con semivida | pierden peso con el tiempo en vez de cortar de golpe |

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
A   = base_max · ( Σ_{v ∈ BASE} w_v · sub_v / Σ w_v ) / 5                          ∈ [0, base_max]
      BASE = finalizados, antiguedad                                (base_max = 3.5)
b_v = balance(sub_v, neutro_v)  ∈ [−1, +1]:  +1 lo mejor · 0 igual que la referencia · −1 lo peor
      neutro_v = sub-score de la referencia p₀ (mixtas) · 5 (negativas: sólo b ≤ 0)
B⁺  = Σ_{v ∈ MIXTAS}            w_v · max(b_v, 0) / Σ w_v                          ∈ [0, 1]
B⁻  = Σ_{v ∈ MIXTAS ∪ NEGATIVAS} w_v · max(−b_v, 0) / Σ w_v                        ∈ [0, 1]
score_comportamental = clip( A + (5 − base_max) · confianza · B⁺ − α · base_max · B⁻ , 0, 5 )
      confianza = min(1, n_aplicables / n_min): lo que suma se gana con evidencia; lo que resta cuenta completo.
Piloto nuevo (activado hace < dias_nuevo) sin servicios → 0.0. Veterano sin servicios → SIN_SCORE.

score_final = min(score_comportamental, tope_regla)   si alguna regla activa tiene efecto "tope"
estado      = BLOQUEADO  si alguna regla activa tiene efecto "bloqueo"
            = RESTRINGIDO si hay un evento activo con activo_restringe
            = OK          en otro caso
```

- **Lectura:** un veterano activo que se comporta igual que el promedio de su tipo vale
  3.5; lo que hace mejor lo sube hasta 5.0; lo que hace peor y sus antecedentes lo bajan
  hasta 0.0. Un recién activado arranca en 0.0 y con 8 servicios limpios está en ~1.7, al
  mes en ~3.4, a los tres meses en ~4.8.
- **Tipos sin mixtas con dato:** donde ninguna mixta aplica o tiene dato no hay con qué
  ganar el margen de +1.5, así que la base llega hasta 5.0 (el motor lo hace solo y lo
  muestra como `base_max = 5`). Hasta el 2026-09-15 ese era el caso de **todo Rent** (un
  veterano Rent típico quedaba en ~4.9 contra 3.5 en B2B); desde el 2026-09-16
  `calificacion_pasajero` aplica en los tres tipos y Rent queda en la misma escala. Un Rent
  sin ninguna nota de pasajero en 180 días sigue cayendo en este caso.
- `α` (`alpha_antecedentes`, por defecto 1.0): intensidad de las pérdidas. Con `α = 1`
  "todo en lo peor" deja el score en 0; con `α = 0.5` pierde como mucho la mitad de la base.
- **Ninguna variable domina**: una mixta puede sumar hasta `1.5 · w_v / Σ w_mixtas` y
  restar hasta `3.5 · w_v / Σ w_comportamiento`; una negativa sólo restar. La base la
  mueven dos variables, así que `max_participacion_peso` se valida por bloque (base ≤ 60 %,
  comportamiento ≤ 35 %).
- **El neutro es la referencia real**: para cancelación `p₀` es la mediana por tipo (35–42 %):
  cancelar como el promedio o menos no mueve nada (es negativa: **cancelar poco no suma**),
  cancelar como el peor décimo (p90) resta −1 de balance. Como el suavizado deja a un
  piloto con poca evidencia en `p₀`, no pierde por lo que todavía no hizo. En Rent, donde
  las demás mixtas no aplican, un piloto sin problemas vale exactamente su base ganada.
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

## 11. Pesos definitivos (separados de la metodología)

Fijados por el usuario en el afinador el **2026-09-16** (`config/pesos.yaml`). Desde ese
momento el afinador los muestra como barras fijas y el servidor ignora cualquier peso que
le manden (y rechaza guardarlos): cambiarlos es una edición a mano del YAML, con commit.
Son proporciones dentro de cada bloque: lo que manda es el porcentaje, no el número.

| Bloque | Variable | B2B | RENT | B2C | Lectura |
|---|---|---:|---:|---:|---|
| Base (suma) | finalizados | 10 | 15 | 15 | Experiencia (satura en el p95 real de 90 días). En B2B es el 67 % de la base |
| Base (suma) | antiguedad | 5 | 10 | 12 | Días desde la activación; satura a los 90 |
| Mixta (±) | alto_valor | 19 | – | 18 | La mixta de más peso en B2B (40 %) y B2C (42 %): balance de cumplimiento × exposición |
| Mixta (±) | recaudo_entregado | 10 | – | 10 | Todos los recaudos: bien suma, novedad/no pago resta (no pago ×2). Referencia 90 % |
| Mixta (±) | cumplimiento_reservas | 10 | – | – | Referencia 90 % |
| Mixta (±) | sin_novedades | 4 | – | 10 | Referencia 90 % |
| Mixta (±) | recaudo_24h | 5 | – | – | Referencia 85 % a tiempo; vencido sin pagar cuenta como tarde |
| Mixta (±) | calificacion_pasajero | – | 5 | 5 | Promedio de notas 1–5 vs. la mediana de su tipo (Rent 4,83 · B2C 4,92). En Rent es la única mixta: acapara todo el margen de +1,5. En B2B la nota es siempre 5: no aplica |
| Negativa (−) | activacion_express | 30 | 27 | 6 | La negativa de más peso en B2B (19 %) y Rent (22 %); se apaga con semivida de 120 días |
| Negativa (−) | expulsion | 20 | 20 | 28 | Histórica (la activa restringe); la de más peso en B2C (19 %) |
| Negativa (−) | cancelacion_piloto | 16 | 13 | 18 | Resta sólo por encima de la mediana real por tipo (p90 = −1); cancelar menos no suma |
| Negativa (−) | invitacion_pibox | 16 | 11 | 14 | |
| Negativa (−) | invitacion_rent | 13 | 16 | 12 | |
| Negativa (−) | conducta_inapropiada | 8 | 14 | 16 | Casos "Con Novedad" confirmados; moderado (tope 5) |
| Negativa (−) | baneo_imei | – | 9 | – | Sólo Rent (la activa restringe) |
| Negativa (−) | suspension_piloto | 5 | 5 | 5 | |
| Negativa (−) | suspension_pasajero | 5 | 5 | 5 | Otro rol |
| | **Σ base / Σ mixtas / Σ negativas** | 15 / 48 / 113 | 25 / 5 / 120 | 27 / 43 / 104 | |

Con estos pesos, el tope de participación de la base subió a 70 % (`max_participacion_peso`),
porque experiencia en B2B queda en 10 de 15. `α = 1`.

Calibración de los parámetros de medición (no de los pesos): correr el motor sobre la población real de 90
días, mirar la distribución de cada sub-score (que no esté todo pegado a 5 ni a 0), fijar
`p₀` en la mediana poblacional de cada tasa y los umbrales de rampa en percentiles
(p. ej. `x₅` = p20, `x₀` = p95 para cancelación), y revisar con Operaciones 20–30 pilotos
conocidos: los que ellos consideran ejemplares deben quedar arriba y los problemáticos
abajo. Si no, mover pesos — no fórmulas.

## 12. Ejemplos numéricos (12 casos ficticios con nombre, corte 2026-09-15; regenerados 2026-09-16 con los pesos definitivos)

Generados con `python3 docs/generar_ejemplos.py` sobre `data/*.csv` (D = desempeño,
P = penalización de antecedentes). `data/` trae además 120 pilotos ficticios sin nombre de
caso (`data/generar_datos_ficticios.py`) para que el ranking top/medio/peores se llene:

| Piloto | Tipo | Caso | Base | +mejor / −peor | Score | Final | Banda | Vigencia | Estado | Observaciones |
|---|---|---|---:|---:|---:|---:|---|---|---|---|
| P001 | B2B | buen comportamiento sostenido | 3.5 | +1.09 / −0.01 | 4.6 | **4.6** | EXCELENTE | DEFINITIVO (1.0) | OK | Entregó bien sus 7 recaudos |
| P002 | RENT | piloto nuevo (12 días), pocos servicios, activación express | 1.0 | +0.00 / −0.73 | 0.3 | **0.3** | EXTREMADAMENTE_CRITICO | PROVISIONAL (0.35) | OK | Piloto NUEVO: activado hace 12 días — arranca en 0.0 y sube con lo que haga; Activado por la vía EXPRESS (menos validación al entrar); Piloto con pocos servicios en la ventana: 7 de 20 necesarios (score provisional) |
| P003 | RENT | suspensión antigua + muchas finalizaciones | 3.5 | +1.26 / −0.01 | 4.8 | **4.8** | EXCELENTE | DEFINITIVO (1.0) | OK | Suspensión como piloto hace 603 días |
| P004 | B2C | comportamiento negativo reciente | 3.0 | +0.00 / −0.81 | 2.2 | **2.2** | DEFICIENTE | DEFINITIVO (1.0) | OK | Suspensión como piloto hace 10 días; Invitación Pibox hace 20 días; Conducta inapropiada confirmada hace 24 días; Novedades frecuentes: sólo 117 de 147 sin novedad y a tiempo (80%); Novedades en servicios de alto valor: 5 de 8 bien; Recaudos sin entregar: 2 de 3 ($245,000); Calificación baja de los pasajeros: 4.10 en 48 servicios |
| P005 | B2B | alto valor con muchas novedades | 3.3 | +0.00 / −0.51 | 2.8 | **2.8** | ACEPTABLE | DEFINITIVO (1.0) | OK ⚠ recaudo_pendiente (1 vencido/s sin pagar) | Novedades frecuentes: sólo 267 de 373 sin novedad y a tiempo (72%); Novedades en servicios de alto valor: 28 de 40 bien; Incumple reservas: 4 de 14; Recaudo vencido sin pagar (1); Recaudos sin entregar: 1 de 4 ($48,000) |
| P006 | RENT | múltiples suspensiones + IMEI baneado | 3.4 | +0.00 / −0.53 | 2.8 | **2.8** | ACEPTABLE | DEFINITIVO (1.0) | BLOQUEADO [baneo_imei] ⚠ imei_compartido | Baneo de IMEI VIGENTE; 3 suspensiones como piloto (última hace 30 días); Baneo de IMEI hace 14 días; Calificación baja de los pasajeros: 4.35 en 151 servicios; Regla activa: imei_compartido |
| P007 | B2C | piloto nuevo (3 días) con cero servicios: arranca en 0.0 | 0.0 | +0.00 / −0.00 | 0.0 | **0.0** | EXTREMADAMENTE_CRITICO | PROVISIONAL (0.0) | OK | Piloto NUEVO: activado hace 3 días — arranca en 0.0 y sube con lo que haga; Piloto con pocos servicios en la ventana: 0 de 20 necesarios (score provisional) |
| P008 | B2B | expulsión histórica (reintegrado) | 3.1 | +0.13 / −0.26 | 2.9 | **2.9** | ACEPTABLE | DEFINITIVO (1.0) | OK ⚠ cancelaciones_en_racha | Expulsión hace 400 días; Regla activa: cancelaciones_en_racha |
| P009 | RENT | una sola cancelación | 3.3 | +0.46 / −0.00 | 3.7 | **3.7** | BUENO | DEFINITIVO (1.0) | OK | — |
| P010 | B2C | muchos servicios de alto valor bien atendidos | 3.5 | +1.50 / −0.00 | 5.0 | **5.0** | EXCELENTE | DEFINITIVO (1.0) | OK | Entregó bien sus 5 recaudos |
| P011 | B2B | cuenta nueva con tope por regla | 1.8 | +0.70 / −0.03 | 2.5 | **2.5** | ACEPTABLE | DEFINITIVO (1.0) | OK ⚠ cuenta_nueva_retiro_alto | Piloto NUEVO: activado hace 20 días — arranca en 0.0 y sube con lo que haga; Suspensión como pasajero hace 76 días; Regla activa: cuenta_nueva_retiro_alto |
| P012 | B2B | recaudos pagados tarde y uno vencido | 3.3 | +0.48 / −0.26 | 3.5 | **3.5** | BUENO | DEFINITIVO (1.0) | OK ⚠ recaudo_pendiente (1 vencido/s sin pagar) | Recaudo vencido sin pagar (1); Recaudos pagados después de 24 h: 2 de 4; Recaudos sin entregar: 1 de 4 ($150,000); Recaudos entregados con novedad (fuera de plazo): 2 de 4 |

Lectura caso por caso (§12 del requerimiento), con los pesos definitivos:

- **Piloto nuevo con pocos servicios** (P002, activado hace 12 días, 7 servicios,
  activación express): **0.3** PROVISIONAL — base chica (antigüedad 12 de 90 días,
  experiencia 7 servicios) y la activación express, que en Rent es la negativa de más peso
  (22 %), le descuenta 0.73. Va a subir solo con cada semana y cada servicio limpio.
- **Piloto nuevo con cero servicios** (P007, activado hace 3 días): **0.0**, provisional.
  Arranca desde abajo; un veterano sin servicios en la ventana, en cambio, queda
  `SIN_SCORE` (inactivo), no 0.0.
- **Sin datos históricos**: cada variable sin fuente sale del cálculo (§6).
- **Suspensión antigua** (P003, hace 600 d con semivida 180): carga 0.1 → descuento 0.01.
- **Múltiples suspensiones** (P006, a 30/90/200 d): carga 2.06 ≥ tope 2 → sub 0, pero con
  suspensiones en 5 de 125 el descuento es −0.14; el IMEI reciente (9 de 125) −0.25.
- **Una sola cancelación** (P009, 1/101): 4.8, prácticamente sin efecto → 3.7 BUENO.
- **Muchas cancelaciones** (P006, 47/309 = 15 %): por debajo de la mediana Rent (34 %) → 0.
- **Muchas finalizaciones** (P003, 400): `finalizados` satura en 5; no sigue sumando.
- **Alto valor bien atendido** (P010, 59/60): alto_valor 4.9 (42 % de las mixtas B2C), 5
  recaudos entregados al toque y calificación 4,97 → 5.0 total.
- **Alto valor con novedades** (P005, 28/40): con alto valor al 40 % de las mixtas B2B, esa
  sola variable resta −0.24 → 2.8 ACEPTABLE aunque no tenga antecedentes — ver desglose.
- **Buen comportamiento sostenido** (P001): 4.6 EXCELENTE (7 recaudos bien, 100 % sin
  novedad, alto valor 25/25).
- **Negativo reciente** (P004): 2 recaudos sin entregar −0.21 y alto valor 5/8 −0.20 pesan
  más que la suspensión de hace 10 días (−0.06: suspensiones son 5 de 104) → 2.2.
- **Variable no aplicable**: en P006 (RENT) `alto_valor`, `sin_novedades`, `reservas`,
  `recaudo_24h` y `recaudo_entregado` figuran como `no_aplica` y no pesan; `calificacion_pasajero`
  sí (4,35 → resta al máximo) y por eso la base de Rent vuelve a topar en 3.5. En P001/P005
  (B2B) la que no aplica es `calificacion_pasajero`.
- **Recaudo tarde / vencido** (P012): en `recaudo_24h` (5 de 48 mixtas) 1 a tiempo, 2 tarde
  y 1 vencido → sub 1.6 + alerta `recaudo_pendiente`; en `recaudo_entregado` (10 de 48) los
  mismos 4 dan 1 bien / 2 con novedad / 1 no pago (pesa doble) → sub 0.6. Las dos restan
  (solapamiento de §3.7b) y aun así queda en 3.5 BUENO porque sus reservas y alto valor
  están por encima de la referencia.
- **Calificación del pasajero**: P003 (4,90 en Rent, referencia 4,83) suma y lo lleva a 4.8
  EXCELENTE — en Rent es la única mixta, así que acapara todo el margen de +1.5; P009 (4,85)
  suma un poco; P004 (4,10 en B2C) y P006 (4,35 en Rent) están por debajo de "lo peor" de su
  tipo y restan el máximo de su peso.

## 13. Ejemplo B2B (P005 — alto valor con novedades, sin antecedentes)
**P005 · Elena Quintero (alto valor con muchas novedades) · B2B** — base 3.34 + 0.00 − 0.51 = 2.83 → **2.8** (ACEPTABLE, DEFINITIVO, estado OK)

| Variable | Bloque | Sub-score | Peso efectivo | Aporte (±) | Cálculo |
|---|---|---:|---:|---:|---|
| suspension_piloto | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=2.0, desde=None, sin_decaimiento=False |
| suspension_pasajero | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=3.0, desde=None, sin_decaimiento=False |
| invitacion_pibox | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0, desde=None, sin_decaimiento=False |
| invitacion_rent | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0, desde=None, sin_decaimiento=False |
| expulsion | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=1.0, desde=None, sin_decaimiento=False |
| baneo_imei | — | — | — | — | *no_aplica* |
| conducta_inapropiada | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=5.0, desde=2026-07-01, sin_decaimiento=True |
| antiguedad | base | 5.00 | 33.3% | +1.17 | dias=700, dias_ref=90, desde=2024-10-15 |
| activacion_express | negativa | 5.00 | 0.0% | +0.00 | express=0 |
| cancelacion_piloto | negativa | 5.00 | 0.0% | +0.00 | x=3, n=194, ventana_dias=180, referencia_p0=0.35, tasa_cruda=0.0155, tasa_ajustada=0.0319, excluidos_no_atribuibles=12 |
| finalizados | base | 4.66 | 66.7% | +2.18 | n=90, n_ref=125, tasa_finalizacion=0.9783 |
| sin_novedades | mixta | 1.63 | 8.3% | -0.05 | x=267, n=373, ventana_dias=365, referencia_p0=0.9, tasa_cruda=0.7158, tasa_ajustada=0.7206 |
| alto_valor | mixta | 1.65 | 39.6% | -0.24 | n_alto_valor=40, ok=28, proporcion=0.4444, exposicion=1.0, cumplimiento_ajustado=0.7222, score_neutro=4.054, score_desempeno=1.652 |
| recaudo_24h | mixta | 2.71 | 10.4% | -0.03 | episodios=1, referencia_p0=0.85, a_tiempo=0, tarde=0, vencidos_sin_pagar=1, pendientes_en_plazo=0, n=1, limite_horas=24.0, tasa_cruda=0.0, tasa_ajustada=0.7083, horas_por_episodio=[None] |
| recaudo_entregado | mixta | 2.78 | 20.8% | -0.08 | recaudos=4, bien=3, novedad=0, no_pago=1, en_plazo=0, n=5.0, peso_no_pago=2.0, plazo_horas_habiles=24.0, ventana_dias=90, referencia_p0=0.9, monto_total=336000.0, monto_no_pagado=48000.0, tasa_cruda=0.6, tasa_ajustada=0.75 |
| calificacion_pasajero | — | — | — | — | *no_aplica* |
| cumplimiento_reservas | mixta | 2.21 | 20.8% | -0.10 | cumplidas=10, ventana_dias=90, referencia_p0=0.9, incumplidas_atrib=4, n=14, no_atribuibles_excluidas=1, tasa_cruda=0.7143, tasa_ajustada=0.7632 |

Cómo se lee: base ganada 3.34 (experiencia +2.18, antigüedad +1.17: en B2B la experiencia es
el 67 % de la base). Nada suma por encima de la referencia (su 2 % de cancelación ya no
premia: la variable sólo resta; la calificación no aplica en B2B). Resta: 28 de 40 servicios
de alto valor bien (−0.24, la mixta de más peso), 4 reservas incumplidas de 14 (−0.10), 1
recaudo de 4 sin entregar (−0.08 en `recaudo_entregado` y −0.03 en `recaudo_24h`) y sólo 72 %
sin novedad (−0.05: con peso 4 de 48 casi no cuenta) → 3.34 − 0.51 = **2.8 ACEPTABLE**. Sin antecedentes; es su propia operación la que la deja ahí. Cupo:
SIN_CUPO — el score daría MEDIO, pero el recaudo vencido sin pagar cierra la compuerta.

## 14. Ejemplo Rent (P006 — múltiples suspensiones, IMEI baneado, regla de bloqueo)
**P006 · Fabián Ospina (múltiples suspensiones + IMEI baneado) · RENT** — base 3.36 + 0.00 − 0.53 = 2.83 → **2.8** (ACEPTABLE, DEFINITIVO, estado BLOQUEADO)

| Variable | Bloque | Sub-score | Peso efectivo | Aporte (±) | Cálculo |
|---|---|---:|---:|---:|---|
| suspension_piloto | negativa | 0.00 | 0.0% | -0.14 | n_eventos=3, en_ventana=3, carga=2.061, tope=2.0, desde=None, sin_decaimiento=False |
| suspension_pasajero | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=3.0, desde=None, sin_decaimiento=False |
| invitacion_pibox | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0, desde=None, sin_decaimiento=False |
| invitacion_rent | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0, desde=None, sin_decaimiento=False |
| expulsion | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=1.0, desde=None, sin_decaimiento=False |
| baneo_imei | negativa | 0.13 | 0.0% | -0.25 | n_eventos=1, en_ventana=1, carga=0.974, tope=1.0, desde=None, sin_decaimiento=False |
| conducta_inapropiada | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=5.0, desde=2026-07-01, sin_decaimiento=True |
| antiguedad | base | 5.00 | 40.0% | +1.40 | dias=800, dias_ref=90, desde=2024-07-07 |
| activacion_express | negativa | 5.00 | 0.0% | +0.00 | express=0 |
| cancelacion_piloto | negativa | 5.00 | 0.0% | +0.00 | x=47, n=309, ventana_dias=180, referencia_p0=0.34, tasa_cruda=0.1521, tasa_ajustada=0.158, excluidos_no_atribuibles=30 |
| finalizados | base | 4.66 | 60.0% | +1.96 | n=120, n_ref=170, tasa_finalizacion=0.8451 |
| sin_novedades | — | — | — | — | *no_aplica* |
| alto_valor | — | — | — | — | *no_aplica* |
| recaudo_24h | — | — | — | — | *no_aplica* |
| recaudo_entregado | — | — | — | — | *no_aplica* |
| calificacion_pasajero | mixta | 0.00 | 100.0% | -0.14 | n=151, suma=657.0, ventana_dias=180, referencia_p0=4.825, promedio_crudo=4.351, promedio_ajustado=4.38 |
| cumplimiento_reservas | — | — | — | — | *no_aplica* |

Cómo se lee: desde el 2026-09-16 Rent tiene una mixta (`calificacion_pasajero`), así que la
base topa en 3.5 como en los demás tipos: 3.36 (antigüedad +1.40, experiencia +1.96). Su 15 %
de cancelación está por debajo de la mediana Rent (34 %) → 0 (no suma ni resta). Resta: tres
suspensiones al tope −0.14 (suspensiones pesan 5 de 125), el IMEI reciente −0.25 y una
calificación de 4,35 en 151 servicios (por debajo del p10 de Rent, 4,61: lo peor) −0.14 →
3.36 − 0.53 = **2.8 ACEPTABLE**. El IMEI
activo lo deja RESTRINGIDO y la regla `imei_compartido` lo deja **BLOQUEADO**: el score se
muestra, el cupo no aplica en Rent y no habilita nada.

## 15. Ejemplo B2C (P004 — comportamiento negativo reciente)
**P004 · Diego Salazar (comportamiento negativo reciente) · B2C** — base 2.99 + 0.00 − 0.81 = 2.18 → **2.2** (DEFICIENTE, DEFINITIVO, estado OK)

| Variable | Bloque | Sub-score | Peso efectivo | Aporte (±) | Cálculo |
|---|---|---:|---:|---:|---|
| suspension_piloto | negativa | 2.59 | 0.0% | -0.06 | n_eventos=1, en_ventana=1, carga=0.962, tope=2.0, desde=None, sin_decaimiento=False |
| suspension_pasajero | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=3.0, desde=None, sin_decaimiento=False |
| invitacion_pibox | negativa | 3.93 | 0.0% | -0.07 | n_eventos=1, en_ventana=1, carga=0.857, tope=4.0, desde=None, sin_decaimiento=False |
| invitacion_rent | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=4.0, desde=None, sin_decaimiento=False |
| expulsion | negativa | 5.00 | 0.0% | +0.00 | n_eventos=0, en_ventana=0, carga=0.0, tope=1.0, desde=None, sin_decaimiento=False |
| baneo_imei | — | — | — | — | *no_aplica* |
| conducta_inapropiada | negativa | 4.00 | 0.0% | -0.08 | n_eventos=1, en_ventana=1, carga=1.0, tope=5.0, desde=2026-07-01, sin_decaimiento=True |
| antiguedad | base | 5.00 | 44.4% | +1.56 | dias=400, dias_ref=90, desde=2025-08-11 |
| activacion_express | negativa | 5.00 | 0.0% | +0.00 | express=0 |
| cancelacion_piloto | negativa | 5.00 | 0.0% | +0.00 | x=18, n=102, ventana_dias=180, referencia_p0=0.42, tasa_cruda=0.1765, tasa_ajustada=0.1982, excluidos_no_atribuibles=10 |
| finalizados | base | 3.70 | 55.6% | +1.44 | n=40, n_ref=150, tasa_finalizacion=0.8 |
| sin_novedades | mixta | 2.74 | 24.3% | -0.08 | x=117, n=147, ventana_dias=365, referencia_p0=0.9, tasa_cruda=0.7959, tasa_ajustada=0.8025 |
| alto_valor | mixta | 2.01 | 39.2% | -0.20 | n_alto_valor=8, ok=5, proporcion=0.2, exposicion=0.8944, cumplimiento_ajustado=0.7308, score_neutro=4.054, score_desempeno=1.767 |
| recaudo_24h | — | — | — | — | *no_aplica* |
| recaudo_entregado | mixta | 0.56 | 24.3% | -0.21 | recaudos=3, bien=1, novedad=0, no_pago=2, en_plazo=0, n=5.0, peso_no_pago=2.0, plazo_horas_habiles=24.0, ventana_dias=90, referencia_p0=0.9, monto_total=280000.0, monto_no_pagado=245000.0, tasa_cruda=0.2, tasa_ajustada=0.55 |
| calificacion_pasajero | mixta | 0.00 | 12.2% | -0.12 | n=48, suma=197.0, ventana_dias=180, referencia_p0=4.917, promedio_crudo=4.104, promedio_ajustado=4.244 |
| cumplimiento_reservas | — | — | — | — | *no_aplica* |

Cómo se lee: base 2.99 (antigüedad +1.56, experiencia +1.44). Su 18 % de cancelación queda
por debajo de la mediana B2C (42 %) → 0. Resta: **2 de 3 recaudos sin entregar** −0.21 (el no
pago pesa doble), 5 de 8 en alto valor −0.20, calificación 4,10 en 48 servicios −0.12 (por
debajo del p10 de B2C, 4,78), 80 % sin novedad −0.08, el caso de **conducta inapropiada
confirmado** hace 24 días −0.08, la invitación −0.07 y la suspensión de hace 10 días −0.06
(suspensiones pesan 5 de 104) → 2.99 − 0.81 = **2.2 DEFICIENTE**.
Dentro de 6 meses, sin nuevos eventos, la suspensión pesará la mitad; los recaudos sin
entregar salen de la ventana a los 90 días — o antes, si los salda.

## 16. Implementación en SQL / Python / Power BI

**Contexto que acompaña al score** (no puntúa, se muestra en el ranking): `driver_id`,
`passenger_id`, nombre real (`passengers`), fecha de activación como piloto y como
pasajero, calificación del **gamification** (BD ClickHouse existente — tabla por ubicar)
y calificación en la **app** (`rating_as_driver__fl`; sólo contexto — NO es el promedio de
lo que ponen los pasajeros, ver §3.7c). Las **observaciones** (piloto nuevo, cancelación alta,
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


## 18. Cupo de confianza en plata (análisis predictivo de monto)

Cuánto **valor declarado** o **recaudo contra entrega** se le puede confiar a un piloto,
como lectura del score (no entra al cálculo). Parámetros en `parametros.yaml → cupo_monto`;
montos en COP:

| Tramo | Score mínimo | Monto | Condiciones extra |
|---|---:|---|---|
| SIN CUPO | < 1.5 | — | también si está RESTRINGIDO/BLOQUEADO, si tiene un **recaudo vencido sin pagar**, o si es **piloto nuevo** |
| MÍNIMO | 1.5 | 20.000 – 60.000 | tope para score **provisional** (pocos servicios) |
| MEDIO | 2.5 | 61.000 – 100.000 | |
| ALTO | 3.5 | 101.000 – 300.000 | |
| MUY ALTO | 4.5 | 301.000 – 1.000.000 | |
| MÁXIMO | 4.5 | **más de 1.000.000** | score definitivo, sin balance negativo en alto valor / recaudo / conducta, y ≥ 10 servicios de alto valor sin novedad (donde aplique) |

Además, si el piloto tiene **novedades en servicios de alto valor** (balance negativo) baja
**un tramo**. El resultado trae los motivos paso a paso ("score 3.6 → ALTO → novedades en
alto valor: un tramo menos → MEDIO") y se muestra en el ranking y en el desglose. Supuesto:
"20 cop a 60 cop" se interpretó como **miles de pesos**; son parámetros.
