-- 01_pilotos.sql → data_real/pilotos.csv
-- Una fila por piloto (bookings.driver_id) × tipo. Ventanas (manejo de tiempos):
--   experiencia y contexto: 90 días (n_*)  ·  cancelación propia: 180 días (vc_*).
-- Verificado: status_cd 4/107/108 finalizado · 100 canceló piloto · 102 usuario · 104 plataforma.
-- SUPUESTOS (a confirmar con Operaciones):
--   tipo: booking con package → mensajería (company_id lleno → B2B, vacío → B2C); sin package → RENT.
--   activación piloto = passengers.enrollment_approval_at; registro pasajero = passengers.created_at.
--   gamification = vw_atr_driver_scoring_with_frauds (new_final_score_pibox / _rent según tipo).
--   sin_novedades, alto_valor y reservas quedan VACÍOS (sin fuente confirmada) → el motor los excluye.
--   calificación del pasajero (2026-09-16): rate_to_driver 1–5 SÓLO en finalizados, 180 días.
--     '' = nunca calificó, '0' = saltó la calificación, y hay cincos en cancelados: todo eso queda fuera.
WITH
  ult AS (
    SELECT _id,
           argMax(toString(driver_id),  _sdc_batched_at) AS drv,
           argMax(status_cd,            _sdc_batched_at) AS st,
           argMax(toString(company_id), _sdc_batched_at) AS cia,
           argMax(ifNull(rate_to_driver, ''), _sdc_batched_at) AS rt,
           min(created_at)                                AS creado
    FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 180 DAY
      AND notEmpty(ifNull(toString(driver_id), ''))
    GROUP BY _id),
  pk AS (
    SELECT DISTINCT toString(booking_id) AS booking_id
    FROM picapmongoprod.packages
    WHERE created_at >= now() - INTERVAL 187 DAY),
  tip AS (
    SELECT u.drv AS drv, u.st AS st, u.rt AS rt, u.creado >= now() - INTERVAL 90 DAY AS en90,
           if(p.booking_id != '', if(notEmpty(ifNull(u.cia, '')), 'B2B', 'B2C'), 'RENT') AS tipo
    FROM ult u LEFT JOIN pk p ON p.booking_id = u._id),
  agg AS (
    SELECT drv AS piloto_id, tipo,
           countIf(st IN (4, 107, 108) AND en90) AS n_finalizados,
           countIf(st = 100 AND en90)            AS n_cancel_piloto,
           countIf(st = 102 AND en90)            AS n_cancel_pasajero,
           countIf(st = 104 AND en90)            AS n_cancel_plataforma,
           countIf(st = 100)                     AS vc_n_cancel_piloto,      -- 180 días
           countIf(st IN (4, 107, 108))          AS vc_n_finalizados,
           countIf(st IN (102, 104))             AS vc_n_no_atribuibles,
           countIf(st IN (4, 107, 108) AND rt IN ('1','2','3','4','5'))                    AS n_calificados,       -- 180 días
           sumIf(toInt32OrZero(rt), st IN (4, 107, 108) AND rt IN ('1','2','3','4','5'))   AS suma_calificaciones
    FROM tip GROUP BY piloto_id, tipo),
  pas AS (
    SELECT _id,
           argMax(ifNull(name, ''),      _sdc_batched_at) AS nom,
           argMax(ifNull(last_name, ''), _sdc_batched_at) AS ape,
           argMax(created_at,            _sdc_batched_at) AS creado,
           argMax(enrollment_approval_at, _sdc_batched_at) AS aprobado,
           argMax(rating_as_driver__fl,  _sdc_batched_at) AS rating_drv,
           argMax(activation_record_cd,  _sdc_batched_at) AS record_cd
    FROM picapmongoprod.passengers
    WHERE _id IN (SELECT piloto_id FROM agg)
    GROUP BY _id),
  -- Activación express COMO PILOTO = passengers.activation_record_cd = 2 (INFERIDO 2026-09-15:
  -- entre pilotos autorizados, el código 2 coincide al 99,97 % con la marca express, casi
  -- nunca tiene agente asignado y es reciente; 1 = activación con validación, 0 = histórico
  -- sin registro). express_activation_for_passenger es la vía express del PASAJERO y el
  -- flag express de driver_enrollment_document_forms es de la plantilla: se descartaron.
  gam AS (
    SELECT driver_id AS gid, final_score, total_score_points, new_final_score_pibox, new_final_score_rent
    FROM picapmongoprod.vw_atr_driver_scoring_with_frauds
    WHERE driver_id IN (SELECT piloto_id FROM agg))
SELECT
  a.piloto_id                                                        AS piloto_id,
  trim(concat(p.nom, ' ', p.ape))                                    AS nombre,
  ''                                                                 AS caso,
  a.tipo                                                             AS tipo,
  a.piloto_id                                                        AS driver_id,
  ''                                                                 AS passenger_id,
  toString(toDate(parseDateTime64BestEffortOrNull(p.aprobado)))      AS activado_piloto,
  toString(toDate(p.creado))                                         AS activado_pasajero,
  if(g.gid IS NULL OR g.gid = '', NULL, if(a.tipo = 'RENT', g.new_final_score_rent, g.new_final_score_pibox)) AS calif_gamification,
  if(g.gid IS NULL OR g.gid = '', NULL, g.total_score_points)        AS gamif_puntos,
  if(g.gid IS NULL OR g.gid = '', NULL, g.final_score)               AS gamif_final,
  toFloat64OrNull(p.rating_drv)                                      AS calif_app,
  toUInt8(ifNull(p.record_cd, 0) = 2)                                AS activacion_express,
  dateDiff('day', toDate(p.creado), today())                         AS dias_antiguedad,
  a.n_finalizados, a.n_cancel_piloto, a.n_cancel_pasajero, a.n_cancel_plataforma,
  0 AS n_otros_atribuibles,
  a.vc_n_cancel_piloto, a.vc_n_finalizados, 0 AS vc_n_otros_atribuibles, a.vc_n_no_atribuibles,
  a.n_calificados, a.suma_calificaciones,
  '' AS vn_n_finalizados, '' AS vn_n_sin_novedad_a_tiempo,
  '' AS n_sin_novedad_a_tiempo, '' AS n_alto_valor, '' AS n_alto_valor_ok,
  '' AS n_res_cumplidas, '' AS n_res_incumplidas_atrib, '' AS n_res_cancel_atrib, '' AS n_res_no_atrib
FROM agg a
LEFT JOIN pas p ON p._id = a.piloto_id
LEFT JOIN gam g ON g.gid = a.piloto_id
ORDER BY a.tipo, a.n_finalizados DESC
FORMAT CSVWithNames
