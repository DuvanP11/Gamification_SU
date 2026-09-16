-- 04_documentos.sql → data_real/documentos.csv
-- Habilitación documental por piloto (NO da puntos: restringe o alerta, ver parametros.yaml → documentos).
--   licencia  : passengers.people_runt_info (JSON del RUNT): estado + mayor fecha de vencimiento.
--   runt_mssg : "No se encontró información…" → licencia no encontrada.
--   policía   : passengers.people_police_records (texto oficial) + último recheck (police_records_rechecks).
--   SOAT/tecno: driver_enrollment_document_form_solutions, ÚLTIMO vencimiento por piloto
--               (los formularios viejos quedan con fechas ya vencidas: se toma el máximo).
WITH
  pil AS (
    SELECT DISTINCT toString(driver_id) AS piloto_id
    FROM picapmongoprod.bookings
    WHERE created_at >= now() - INTERVAL 90 DAY AND created_at <= now() AND notEmpty(ifNull(toString(driver_id), ''))),
  pas AS (
    SELECT _id,
           argMax(ifNull(people_runt_info, ''),      _sdc_batched_at) AS runt,
           argMax(ifNull(runt_mssg, ''),             _sdc_batched_at) AS runt_msg,
           argMax(ifNull(people_police_records, ''), _sdc_batched_at) AS pol,
           argMax(last_time_runt_updated,            _sdc_batched_at) AS runt_upd,
           argMax(last_time_police_updated,          _sdc_batched_at) AS pol_upd
    FROM picapmongoprod.passengers
    WHERE _id IN (SELECT piloto_id FROM pil)
    GROUP BY _id),
  rck AS (
    SELECT toString(passenger_id) AS pid,
           argMax(has_police_records_after, requested_at) AS nuevo,
           max(requested_at) AS ultimo
    FROM picapmongoprod.police_records_rechecks
    WHERE passenger_id IN (SELECT piloto_id FROM pil)
    GROUP BY pid),
  frm AS (
    SELECT toString(passenger_id) AS pid,
           max(soat_expiration_date)          AS soat_vence,
           max(tecnomecanica_expiration_date) AS tecno_vence
    FROM picapmongoprod.driver_enrollment_document_form_solutions
    WHERE passenger_id IN (SELECT piloto_id FROM pil)
    GROUP BY pid)
SELECT
  p._id AS piloto_id,
  JSONExtractString(p.runt, 'active_licenses', 'status')                                AS licencia_estado,
  toString(arrayMax(arrayFilter(x -> x IS NOT NULL,
      arrayMap(x -> parseDateTimeOrNull(JSONExtractString(x, 'expiration_date'), '%d/%m/%Y'),
               JSONExtractArrayRaw(p.runt, 'active_licenses', 'details')))))            AS licencia_vence,
  arrayStringConcat(arrayMap(x -> JSONExtractString(x, 'category'),
                             JSONExtractArrayRaw(p.runt, 'active_licenses', 'details')), '/') AS licencia_categorias,
  if(JSONExtractRaw(p.runt, 'user_info', 'driver_state') = 'false', 0, if(p.runt = '', NULL, 1)) AS runt_driver_state,
  p.runt_msg                                                                            AS runt_mssg,
  toString(toDate(parseDateTimeBestEffortOrNull(p.runt_upd)))                           AS runt_consultado,
  multiIf(JSONExtractRaw(p.pol, 'has_police_records') = 'true', 1,
          position(JSONExtractString(p.pol, 'mssg'), 'NO TIENE ASUNTOS PENDIENTES') > 0, 0,
          NULL)                                                                         AS policia_pendientes,
  toString(toDate(parseDateTimeBestEffortOrNull(p.pol_upd)))                            AS policia_consultado,
  if(r.pid = '', NULL, toUInt8(r.nuevo))                                                AS policia_recheck_nuevo,
  toString(toDate(r.ultimo))                                                            AS policia_recheck_fecha,
  toString(toDate(f.soat_vence))                                                        AS soat_vence,
  toString(toDate(f.tecno_vence))                                                       AS tecno_vence
FROM pas p
LEFT JOIN rck r ON r.pid = p._id
LEFT JOIN frm f ON f.pid = p._id
FORMAT CSVWithNames
