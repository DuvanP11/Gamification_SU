-- 05_suspensiones.sql → data_real/eventos_suspensiones.csv
-- Historial de suspensiones de piloto CON FECHA (driver_suspensions): alimenta el bloque de
-- antecedentes con decaimiento. activo = permanente o todavía no termina.
-- origen='historial' hace que el motor descarte el flag sin fecha de 02_eventos para el mismo piloto.
SELECT toString(driver_id) AS piloto_id,
       'suspension_piloto' AS tipo_evento,
       toString(toDate(ifNull(starts_at, created_at))) AS fecha,
       if(ifNull(permanent, false) OR ifNull(ends_at, toDateTime64('1970-01-01', 3)) > now(), 1, 0) AS activo,
       '' AS severidad,
       'historial' AS origen,
       ifNull(toString(rule_id), '') AS rule_id,
       ifNull(toString(penalizations), '') AS penalizations,
       ifNull(toString(status_cd), '') AS status_cd,
       substring(ifNull(message, ''), 1, 120) AS mensaje
FROM (
  SELECT _id,
         argMax(driver_id,     _sdc_batched_at) AS driver_id,
         argMax(starts_at,     _sdc_batched_at) AS starts_at,
         argMax(ends_at,       _sdc_batched_at) AS ends_at,
         argMax(created_at,    _sdc_batched_at) AS created_at,
         argMax(permanent,     _sdc_batched_at) AS permanent,
         argMax(rule_id,       _sdc_batched_at) AS rule_id,
         argMax(penalizations, _sdc_batched_at) AS penalizations,
         argMax(status_cd,     _sdc_batched_at) AS status_cd,
         argMax(message,       _sdc_batched_at) AS message
  FROM picapmongoprod.driver_suspensions
  WHERE created_at >= now() - INTERVAL 730 DAY
  GROUP BY _id)
WHERE notEmpty(ifNull(toString(driver_id), ''))
  AND toString(driver_id) IN (
    SELECT DISTINCT toString(driver_id) FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 90 DAY AND notEmpty(ifNull(toString(driver_id), '')))
ORDER BY piloto_id, fecha
FORMAT CSVWithNames
