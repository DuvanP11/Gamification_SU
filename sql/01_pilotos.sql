-- 01_pilotos.sql → data_real/pilotos.csv
-- Una fila por piloto (bookings.driver_id) × tipo, ventana de 90 días.
-- Verificado: status_cd 4/107/108 finalizado · 100 canceló piloto · 102 usuario · 104 plataforma.
-- SUPUESTOS (a confirmar con Operaciones):
--   tipo: booking con package → mensajería (company_id lleno → B2B, vacío → B2C); sin package → RENT.
--   activación piloto = passengers.enrollment_approval_at; registro pasajero = passengers.created_at.
--   gamification = vw_atr_driver_scoring_with_frauds (new_final_score_pibox / _rent según tipo).
--   sin_novedades, alto_valor y reservas quedan VACÍOS (sin fuente confirmada) → el motor los excluye.
WITH
  ult AS (
    SELECT _id,
           argMax(toString(driver_id),  _sdc_batched_at) AS drv,
           argMax(status_cd,            _sdc_batched_at) AS st,
           argMax(toString(company_id), _sdc_batched_at) AS cia
    FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 90 DAY
      AND notEmpty(ifNull(toString(driver_id), ''))
    GROUP BY _id),
  pk AS (
    SELECT DISTINCT toString(booking_id) AS booking_id
    FROM picapmongoprod.packages
    WHERE created_at >= now() - INTERVAL 97 DAY),
  tip AS (
    SELECT u.drv AS drv, u.st AS st,
           if(p.booking_id != '', if(notEmpty(ifNull(u.cia, '')), 'B2B', 'B2C'), 'RENT') AS tipo
    FROM ult u LEFT JOIN pk p ON p.booking_id = u._id),
  agg AS (
    SELECT drv AS piloto_id, tipo,
           countIf(st IN (4, 107, 108)) AS n_finalizados,
           countIf(st = 100)            AS n_cancel_piloto,
           countIf(st = 102)            AS n_cancel_pasajero,
           countIf(st = 104)            AS n_cancel_plataforma
    FROM tip GROUP BY piloto_id, tipo),
  pas AS (
    SELECT _id,
           argMax(ifNull(name, ''),      _sdc_batched_at) AS nom,
           argMax(ifNull(last_name, ''), _sdc_batched_at) AS ape,
           argMax(created_at,            _sdc_batched_at) AS creado,
           argMax(enrollment_approval_at, _sdc_batched_at) AS aprobado,
           argMax(rating_as_driver__fl,  _sdc_batched_at) AS rating_drv
    FROM picapmongoprod.passengers
    WHERE _id IN (SELECT piloto_id FROM agg)
    GROUP BY _id),
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
  dateDiff('day', toDate(p.creado), today())                         AS dias_antiguedad,
  a.n_finalizados, a.n_cancel_piloto, a.n_cancel_pasajero, a.n_cancel_plataforma,
  0 AS n_otros_atribuibles,
  '' AS n_sin_novedad_a_tiempo, '' AS n_alto_valor, '' AS n_alto_valor_ok,
  '' AS n_res_cumplidas, '' AS n_res_incumplidas_atrib, '' AS n_res_cancel_atrib, '' AS n_res_no_atrib
FROM agg a
LEFT JOIN pas p ON p._id = a.piloto_id
LEFT JOIN gam g ON g.gid = a.piloto_id
ORDER BY a.tipo, a.n_finalizados DESC
FORMAT CSVWithNames
