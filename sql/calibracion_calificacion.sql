-- calibracion_calificacion.sql — percentiles poblacionales del promedio de rate_to_driver
-- (1–5, sólo finalizados, 180 días) por tipo, para fijar p0 / x_score0 / x_score5 de
-- `calificacion_pasajero` en config/parametros.yaml (pilotos con ≥ 20 notas).
--   p0 = mediana · x_score5 = p80 · x_score0 = p10
WITH
  ult AS (
    SELECT _id,
           argMax(toString(driver_id),  _sdc_batched_at) AS drv,
           argMax(status_cd,            _sdc_batched_at) AS st,
           argMax(toString(company_id), _sdc_batched_at) AS cia,
           argMax(ifNull(rate_to_driver, ''), _sdc_batched_at) AS rt
    FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 180 DAY AND notEmpty(ifNull(toString(driver_id), ''))
    GROUP BY _id),
  pk AS (SELECT DISTINCT toString(booking_id) AS booking_id FROM picapmongoprod.packages WHERE created_at >= now() - INTERVAL 187 DAY),
  por_piloto AS (
    SELECT u.drv, if(p.booking_id != '', if(notEmpty(ifNull(u.cia, '')), 'B2B', 'B2C'), 'RENT') AS tipo,
           count() AS n, avg(toInt32OrZero(u.rt)) AS prom
    FROM ult u LEFT JOIN pk p ON p.booking_id = u._id
    WHERE u.st IN (4, 107, 108) AND u.rt IN ('1','2','3','4','5')
    GROUP BY u.drv, tipo HAVING n >= 20)
SELECT tipo, count() AS pilotos,
       round(quantile(0.10)(prom), 3) AS p10, round(quantile(0.20)(prom), 3) AS p20,
       round(quantile(0.50)(prom), 3) AS p50, round(quantile(0.80)(prom), 3) AS p80,
       round(quantile(0.90)(prom), 3) AS p90, round(avg(prom), 3) AS media
FROM por_piloto GROUP BY tipo ORDER BY tipo
FORMAT PrettyCompact
