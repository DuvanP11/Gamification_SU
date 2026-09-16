-- 03_recaudos.sql → data_real/recaudos.csv
-- TODOS los recaudos contra entrega que el piloto tuvo que entregar (B2B/B2C), 90 días.
-- (Hasta 2026-09-15 sólo se exportaban los NO abonados en el momento; ahora salen todos y
--  el motor filtra: recaudo_24h usa los tardíos vía fecha_abono, recaudo_entregado usa
--  todos vía fecha_saldado.)
--   recaudo       = pata NEGATIVA de WalletAccountCounterDeliveryTransaction CON package_id
--                   (la compensación en lote viene sin package_id — ver memoria del portal).
--   fecha_abono   = primera pata POSITIVA posterior del mismo booking (criterio original).
--   fecha_saldado = primera transacción (cualquier tipo) de la MISMA billetera, desde el
--                   recaudo inclusive, con amount_after_transaction ≥ 0: la billetera Picash
--                   del piloto dejó de estar en rojo. Es el criterio del portal
--                   (RecaudosDeudaService: "saldado = la billetera volvió a cero"). Vacío = sigue en rojo.
--   monto         = COP del recaudo (positivo).
WITH
  tx AS (
    SELECT _id,
           argMax(toString(booking_id), _sdc_batched_at) AS bkg,
           argMax(toString(package_id), _sdc_batched_at) AS pkg,
           argMax(toString(account_id), _sdc_batched_at) AS acct,
           argMax(toFloat64OrZero(JSONExtractString(amount, 'cents')), _sdc_batched_at) AS cents,
           argMax(created_at, _sdc_batched_at) AS ts
    FROM picapmongoprod.wallet_account_transactions
    WHERE _type = 'WalletAccountCounterDeliveryTransaction' AND created_at >= now() - INTERVAL 90 DAY AND created_at <= now()
    GROUP BY _id),
  rec AS (
    SELECT bkg, any(acct) AS acct, min(ts) AS fecha_recaudo, -sum(cents) / 100 AS monto
    FROM tx WHERE cents < 0 AND notEmpty(ifNull(pkg, ''))
    GROUP BY bkg),
  abo AS (
    SELECT t.bkg AS bkg, min(t.ts) AS fecha_abono
    FROM tx t INNER JOIN rec r ON r.bkg = t.bkg
    WHERE t.cents > 0 AND t.ts > r.fecha_recaudo
    GROUP BY t.bkg),
  -- Movimientos de las billeteras con recaudo: cuándo volvió cada una a ≥ 0.
  mov AS (
    SELECT acct, ts
    FROM (
      SELECT _id,
             argMax(toString(account_id), _sdc_batched_at) AS acct,
             argMax(created_at, _sdc_batched_at) AS ts,
             argMax(toFloat64OrNull(JSONExtractString(amount_after_transaction, 'cents')), _sdc_batched_at) AS aat,
             argMax(length(amount_after_transaction), _sdc_batched_at) AS len_aat
      FROM picapmongoprod.wallet_account_transactions
      WHERE account_id IN (SELECT acct FROM rec) AND created_at >= now() - INTERVAL 90 DAY AND created_at <= now()
      GROUP BY _id)
    WHERE len_aat > 2 AND aat >= -1),
  sal AS (
    SELECT r.bkg AS bkg, min(m.ts) AS fecha_saldado
    FROM rec r INNER JOIN mov m ON m.acct = r.acct
    WHERE m.ts >= r.fecha_recaudo
    GROUP BY r.bkg),
  bk AS (
    SELECT _id, argMax(toString(driver_id), _sdc_batched_at) AS drv
    FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 97 DAY AND created_at <= now() AND _id IN (SELECT bkg FROM rec)
    GROUP BY _id)
SELECT bk.drv AS piloto_id,
       r.bkg  AS booking_id,
       formatDateTime(toTimeZone(r.fecha_recaudo, 'America/Bogota'), '%Y-%m-%d %H:%i:%S') AS fecha_recaudo,
       round(r.monto, 2) AS monto,
       if(a.fecha_abono IS NULL, '',
          formatDateTime(toTimeZone(a.fecha_abono, 'America/Bogota'), '%Y-%m-%d %H:%i:%S')) AS fecha_abono,
       if(s.fecha_saldado IS NULL, '',
          formatDateTime(toTimeZone(s.fecha_saldado, 'America/Bogota'), '%Y-%m-%d %H:%i:%S')) AS fecha_saldado
FROM rec r
INNER JOIN bk ON bk._id = r.bkg
LEFT JOIN abo a ON a.bkg = r.bkg
LEFT JOIN sal s ON s.bkg = r.bkg
WHERE notEmpty(bk.drv)
FORMAT CSVWithNames
