-- sql/extraccion_clickhouse.sql — ESQUELETO de extracción para alimentar data/pilotos.csv
-- y data/eventos.csv desde picapmongoprod. NO está verificado contra ClickHouse todavía:
-- antes de usarlo correrlo con curl (ver README) y ajustar nombres.
--
-- Lo que SÍ está verificado (portal de Monitoreo, 2026-09-10):
--   bookings.status_cd: 4/107/108 finalizado · 100 canceló el PILOTO · 102 canceló el
--   USUARIO · 104 plataforma · 101 expirado sin piloto. driver_id identifica al piloto.
--   passengers: is_driver_suspended, suspended, expelled (strings 'true'/'1').
--   picapmongoprod.passenger_suspensions existe (suspensiones con fecha).
--   Recaudo: wallet_account_transactions._type = 'WalletAccountCounterDeliveryTransaction',
--   recaudo = pata negativa CON package_id; abono = pata positiva que la cierra.
-- Lo que FALTA confirmar: campo de tipo de servicio (B2B / RENT / B2C), valor declarado,
-- flag de novedad y de "a tiempo", reservas, invitaciones, baneo IMEI, tabla del
-- gamification y campo de calificación en la app, fechas de activación piloto/pasajero.

-- ── 1. Agregados de servicios por piloto × tipo, ventana de 90 días ─────────────
WITH toDate(now()) - 90 AS desde
SELECT
    toString(b.driver_id)                                            AS piloto_id,
    /* TODO: derivar el tipo: B2B / RENT / B2C (¿b.service_type? ¿company_id? ¿Pibox?) */
    'RENT'                                                            AS tipo,
    countIf(b.status_cd IN (4, 107, 108))                             AS n_finalizados,
    countIf(b.status_cd = 100)                                        AS n_cancel_piloto,
    countIf(b.status_cd = 102)                                        AS n_cancel_pasajero,
    countIf(b.status_cd = 104)                                        AS n_cancel_plataforma,
    0                                                                 AS n_otros_atribuibles,
    /* TODO B2B/B2C: countIf(finalizado AND sin_novedad AND a_tiempo) */ NULL AS n_sin_novedad_a_tiempo,
    /* TODO B2B/B2C: countIf(finalizado AND valor_declarado >= umbral) */ NULL AS n_alto_valor,
    /* TODO B2B/B2C: countIf(alto valor AND sin novedad AND a tiempo)  */ NULL AS n_alto_valor_ok,
    /* TODO B2B: reservas cumplidas / incumplidas atribuibles / canceladas atribuibles / no atribuibles */
    NULL AS n_res_cumplidas, NULL AS n_res_incumplidas_atrib, NULL AS n_res_cancel_atrib, NULL AS n_res_no_atrib
FROM picapmongoprod.bookings AS b
WHERE b.created_at >= desde
  AND notEmpty(ifNull(toString(b.driver_id), ''))
GROUP BY piloto_id, tipo
FORMAT CSVWithNames;

-- ── 1b. Contexto del piloto (nombre real, ids, activaciones, calificaciones) ─────
-- SELECT toString(p._id) AS passenger_id, /* driver_id: ¿p.driver_id? */,
--        concat(p.name, ' ', p.last_name) AS nombre,           -- TODO: nombres reales de columnas
--        toDate(p.created_at) AS activado_pasajero,
--        /* TODO */ NULL AS activado_piloto,
--        /* TODO: tabla del gamification en CH */ NULL AS calif_gamification,
--        /* TODO: rating en la app (¿p.rating? ¿drivers.rating?) */ NULL AS calif_app
-- FROM picapmongoprod.passengers p FINAL

-- ── 1c. Recaudos no abonados en el momento (data/recaudos.csv) ──────────────────
-- WITH rec AS (
--   SELECT booking_id, package_id, account_id, min(created_at) AS fecha_recaudo
--   FROM picapmongoprod.wallet_account_transactions
--   WHERE _type = 'WalletAccountCounterDeliveryTransaction'
--     AND toFloat64OrZero(JSONExtractString(amount, 'cents')) < 0
--     AND notEmpty(ifNull(toString(package_id), ''))          -- excluye el lote de compensación
--     AND created_at >= toDate(now()) - 90
--   GROUP BY booking_id, package_id, account_id),
-- abono AS (
--   SELECT booking_id, account_id, min(created_at) AS fecha_abono
--   FROM picapmongoprod.wallet_account_transactions
--   WHERE _type = 'WalletAccountCounterDeliveryTransaction'
--     AND toFloat64OrZero(JSONExtractString(amount, 'cents')) > 0
--   GROUP BY booking_id, account_id)
-- SELECT /* piloto */ rec.account_id, rec.fecha_recaudo, abono.fecha_abono
-- FROM rec LEFT JOIN abono USING (booking_id, account_id)
-- WHERE abono.fecha_abono IS NULL OR abono.fecha_abono > rec.fecha_recaudo + INTERVAL 1 MINUTE  -- "no pagó en el momento"
-- FORMAT CSVWithNames;

-- ── 2. Eventos disciplinarios (una fila por evento) ─────────────────────────────
-- SELECT toString(passenger_id) AS piloto_id, 'suspension_piloto' AS tipo_evento,
--        toDate(created_at) AS fecha, if(activa, 1, 0) AS activo, '' AS severidad
-- FROM picapmongoprod.passenger_suspensions
-- WHERE created_at >= toDate(now()) - 730
-- UNION ALL  -- expulsiones: passengers.expelled = 'true' → activo=1 (fecha: ¿updated_at?)
-- UNION ALL  -- baneo IMEI: sessions.active = 'false' con imei… (definición por confirmar)
-- FORMAT CSVWithNames;
