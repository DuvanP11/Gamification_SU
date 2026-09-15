-- Columnas de passenger_suspensions (histórico de suspensiones con fecha) y de
-- cualquier tabla que suene a invitaciones / IMEI, para completar 02_eventos.sql.
SELECT table, name AS columna, type
FROM system.columns
WHERE database = 'picapmongoprod'
  AND (table = 'passenger_suspensions' OR table ILIKE '%invit%' OR table ILIKE '%imei%' OR table ILIKE '%ban%'
       OR (table = 'passengers' AND (name ILIKE '%expel%' OR name ILIKE '%suspend%')))
ORDER BY table, name
FORMAT PrettyCompact
