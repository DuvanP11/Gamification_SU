-- sql/extraccion_clickhouse.sql — ESQUELETO de extracción para alimentar data/pilotos.csv
-- y data/eventos.csv desde picapmongoprod. NO está verificado contra ClickHouse todavía:
-- antes de usarlo correrlo con curl (ver README) y ajustar nombres.
--
-- Lo que SÍ está verificado (portal de Monitoreo, 2026-09-10):
--   bookings.status_cd: 4/107/108 finalizado · 100 canceló el PILOTO · 102 canceló el
--   USUARIO · 104 plataforma · 101 expirado sin piloto. driver_id identifica al piloto.
--   passengers: is_driver_suspended, suspended, expelled (strings 'true'/'1').
--   picapmongoprod.passenger_suspensions existe (suspensiones con fecha).
-- Lo que FALTA confirmar: campo de tipo de servicio (B2B / RENT / B2C), valor declarado,
-- flag de novedad y de "a tiempo", reservas, invitaciones, bloqueo 24 h, baneo IMEI.

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

-- ── 2. Eventos disciplinarios (una fila por evento) ─────────────────────────────
-- SELECT toString(passenger_id) AS piloto_id, 'suspension_piloto' AS tipo_evento,
--        toDate(created_at) AS fecha, if(activa, 1, 0) AS activo, '' AS severidad
-- FROM picapmongoprod.passenger_suspensions
-- WHERE created_at >= toDate(now()) - 730
-- UNION ALL  -- expulsiones: passengers.expelled = 'true' → activo=1 (fecha: ¿updated_at?)
-- UNION ALL  -- baneo IMEI: sessions.active = 'false' con imei… (definición por confirmar)
-- FORMAT CSVWithNames;
