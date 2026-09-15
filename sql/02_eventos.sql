-- 02_eventos.sql → data_real/eventos.csv
-- Estado ACTUAL de bloqueo desde passengers (flags, sin fecha): suspensión de piloto,
-- suspensión de usuario y expulsión vigentes → activo=1 con fecha = hoy.
-- El HISTÓRICO con fecha (passenger_suspensions) y las invitaciones quedan pendientes
-- de conocer sus columnas (ver sql/00_descubrir_suspensiones.sql).
WITH
  pil AS (
    SELECT DISTINCT toString(driver_id) AS piloto_id
    FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 90 DAY AND notEmpty(ifNull(toString(driver_id), ''))),
  pas AS (
    SELECT _id,
           argMax(lower(ifNull(toString(is_driver_suspended), '')), _sdc_batched_at) AS ds,
           argMax(lower(ifNull(toString(suspended), '')),           _sdc_batched_at) AS us,
           argMax(lower(ifNull(toString(expelled), '')),            _sdc_batched_at) AS ex
    FROM picapmongoprod.passengers
    WHERE _id IN (SELECT piloto_id FROM pil)
    GROUP BY _id)
SELECT _id AS piloto_id, tipo_evento, toString(today()) AS fecha, 1 AS activo, '' AS severidad
FROM (
  SELECT _id, 'suspension_piloto'   AS tipo_evento FROM pas WHERE ds IN ('true', '1')
  UNION ALL
  SELECT _id, 'suspension_pasajero' AS tipo_evento FROM pas WHERE us IN ('true', '1')
  UNION ALL
  SELECT _id, 'expulsion'           AS tipo_evento FROM pas WHERE ex IN ('true', '1'))
FORMAT CSVWithNames
