-- 03_recaudos.sql → data_real/recaudos.csv
-- Recaudos contra entrega que el piloto NO abonó en el momento (B2B):
-- recaudo = pata NEGATIVA con package_id (la compensación en lote viene sin package_id);
-- abono   = primera pata POSITIVA posterior del mismo booking. Ventana 90 días.
WITH
  tx AS (
    SELECT _id,
           argMax(toString(booking_id), _sdc_batched_at) AS booking_id,
           argMax(toString(package_id), _sdc_batched_at) AS package_id,
           argMax(toFloat64OrZero(JSONExtractString(amount, 'cents')), _sdc_batched_at) AS cents,
           argMax(created_at, _sdc_batched_at) AS created_at
    FROM picapmongoprod.wallet_account_transactions
    WHERE _type = 'WalletAccountCounterDeliveryTransaction' AND created_at >= now() - INTERVAL 90 DAY
    GROUP BY _id),
  rec AS (
    SELECT booking_id, min(created_at) AS fecha_recaudo
    FROM tx WHERE cents < 0 AND notEmpty(ifNull(package_id, ''))
    GROUP BY booking_id),
  abo AS (
    SELECT booking_id, min(created_at) AS fecha_abono
    FROM tx WHERE cents > 0
    GROUP BY booking_id),
  bk AS (
    SELECT _id, argMax(toString(driver_id), _sdc_batched_at) AS driver_id
    FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 97 DAY AND _id IN (SELECT booking_id FROM rec)
    GROUP BY _id)
SELECT bk.driver_id AS piloto_id,
       formatDateTime(toTimeZone(r.fecha_recaudo, 'America/Bogota'), '%Y-%m-%d %H:%i:%S') AS fecha_recaudo,
       if(a.fecha_abono IS NULL OR a.fecha_abono <= r.fecha_recaudo, '',
          formatDateTime(toTimeZone(a.fecha_abono, 'America/Bogota'), '%Y-%m-%d %H:%i:%S')) AS fecha_abono
FROM rec r
INNER JOIN bk ON bk._id = r.booking_id
LEFT JOIN abo a ON a.booking_id = r.booking_id
WHERE notEmpty(bk.driver_id)
  AND (a.fecha_abono IS NULL OR a.fecha_abono > r.fecha_recaudo + INTERVAL 1 MINUTE)   -- "no pagó en el momento"
FORMAT CSVWithNames
