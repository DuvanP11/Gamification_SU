-- 03_recaudos.sql → data_real/recaudos.csv
-- Recaudos contra entrega que el piloto NO abonó en el momento (B2B):
-- recaudo = pata NEGATIVA con package_id (la compensación en lote viene sin package_id);
-- abono   = primera pata POSITIVA posterior del mismo booking. Ventana 90 días.
WITH
  tx AS (
    SELECT _id,
           argMax(toString(booking_id), _sdc_batched_at) AS bkg,
           argMax(toString(package_id), _sdc_batched_at) AS pkg,
           argMax(toFloat64OrZero(JSONExtractString(amount, 'cents')), _sdc_batched_at) AS cents,
           argMax(created_at, _sdc_batched_at) AS ts
    FROM picapmongoprod.wallet_account_transactions
    WHERE _type = 'WalletAccountCounterDeliveryTransaction' AND created_at >= now() - INTERVAL 90 DAY
    GROUP BY _id),
  rec AS (
    SELECT bkg, min(ts) AS fecha_recaudo
    FROM tx WHERE cents < 0 AND notEmpty(ifNull(pkg, ''))
    GROUP BY bkg),
  abo AS (
    SELECT bkg, min(ts) AS fecha_abono
    FROM tx WHERE cents > 0
    GROUP BY bkg),
  bk AS (
    SELECT _id, argMax(toString(driver_id), _sdc_batched_at) AS drv
    FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 97 DAY AND _id IN (SELECT bkg FROM rec)
    GROUP BY _id)
SELECT bk.drv AS piloto_id,
       formatDateTime(toTimeZone(r.fecha_recaudo, 'America/Bogota'), '%Y-%m-%d %H:%i:%S') AS fecha_recaudo,
       if(a.fecha_abono IS NULL OR a.fecha_abono <= r.fecha_recaudo, '',
          formatDateTime(toTimeZone(a.fecha_abono, 'America/Bogota'), '%Y-%m-%d %H:%i:%S')) AS fecha_abono
FROM rec r
INNER JOIN bk ON bk._id = r.bkg
LEFT JOIN abo a ON a.bkg = r.bkg
WHERE notEmpty(bk.drv)
  AND (a.fecha_abono IS NULL OR a.fecha_abono > r.fecha_recaudo + INTERVAL 1 MINUTE)   -- "no pagó en el momento"
FORMAT CSVWithNames
