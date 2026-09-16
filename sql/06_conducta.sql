-- 06_conducta.sql → data_real/eventos_conducta.csv
-- Acoso / hostigamiento CONFIRMADO: casos de dashboard_conducta_listas donde el sujeto es
-- el PILOTO y el analista marcó novedad = 'con_novedad'. Un evento por (piloto, día del
-- caso); subtipo = classification (ABUSIVE_LANGUAGE / PROSTITUTION_FRAUD) para poder
-- pesarlos distinto. Histórico completo desde que arrancó la revisión.
SELECT subject_id                                   AS piloto_id,
       'conducta_inapropiada'                       AS tipo_evento,
       toString(run_date)                           AS fecha,
       0                                            AS activo,
       ''                                           AS severidad,
       'historial'                                  AS origen,
       any(classification)                          AS subtipo,
       any(tipo_alerta)                             AS tipo_alerta,
       uniqExactIf(booking_id, booking_id != '')    AS n_bookings,
       arrayStringConcat(arrayDistinct(groupArrayIf(afectado_id, afectado_id != '')), '|') AS afectados,
       any(revisado_por)                            AS revisado_por,
       toString(max(revisado_en))                   AS revisado_en
FROM picapmongoprod.dashboard_conducta_listas FINAL
WHERE sujeto_rol = 'Piloto' AND novedad = 'con_novedad' AND run_date <= today()
GROUP BY subject_id, run_date
ORDER BY piloto_id, fecha
FORMAT CSVWithNames
