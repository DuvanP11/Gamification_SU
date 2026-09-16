# score/ch.py — conexión en vivo a ClickHouse para el afinador / la web.
#
# Tres usos:
#   1. extraer(corte): corre sql/01..06 ANCLADOS a una fecha de corte (now()/today() se
#      reemplazan por esa fecha, con tope superior) y deja los CSV en un directorio caché
#      por fecha. Así el ranking "al día de hoy" y el "a fin de julio" salen de la misma
#      metodología: cambia el ancla de las ventanas, no las fórmulas.
#   2. buscar(tipo, valor): quién es el sujeto (id, cédula, placa, celular, correo) —
#      mismas condiciones que Consulta de Datos del portal de Monitoreo.
#   3. hoja_de_vida(id): la ficha completa (identidad, estado, bloqueos, última conexión,
#      placas, servicios), portada de las queries del portal.
#
# Credenciales por entorno: CH_URL, CH_USER, CH_PASSWORD (obligatoria para activar el
# modo en vivo). Sin CH_PASSWORD el afinador sigue en modo CSV y no toca la red.
from __future__ import annotations
import csv
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CH_URL = os.environ.get("CH_URL", "https://clickhouse.picap.io:8443/?database=picapmongoprod")
CH_USER = os.environ.get("CH_USER", "dperilla")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "")

# Orden y salida de la extracción (misma tabla que refrescar_datos.sh).
EXTRACCION = [("01_pilotos.sql", "pilotos.csv"), ("02_eventos.sql", "eventos.csv"),
              ("03_recaudos.sql", "recaudos.csv"), ("04_documentos.sql", "documentos.csv"),
              ("05_suspensiones.sql", "eventos_suspensiones.csv"), ("06_conducta.sql", "eventos_conducta.csv")]

# Nombre de la columna de placa en vehicles: no es igual en todos los entornos, se
# detecta contra system.columns (igual que ConsultaDatosController.col_placa).
PLACA_CANDIDATAS = ("plate", "placa", "license_plate", "plate_number", "vehicle_plate")
_col_placa: str | None | bool = False   # False = todavía no se buscó


class ErrorCH(RuntimeError):
    pass


def configurado() -> bool:
    return bool(CH_PASSWORD)


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace("'", "\\'")


def consultar(sql: str, formato: str = "JSONEachRow", timeout: int = 180):
    """Corre SQL por HTTP. JSONEachRow → list[dict]; cualquier otro formato → texto."""
    if not configurado():
        raise ErrorCH("ClickHouse no está configurado: falta CH_PASSWORD")
    cuerpo = sql.rstrip().rstrip(";")
    if not re.search(r"\bFORMAT\s+\w+\s*$", cuerpo, re.I):
        cuerpo += f"\nFORMAT {formato}"
    req = urllib.request.Request(CH_URL, data=cuerpo.encode("utf-8"), method="POST")
    req.add_header("X-ClickHouse-User", CH_USER)
    req.add_header("X-ClickHouse-Key", CH_PASSWORD)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            texto = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ErrorCH(f"ClickHouse HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:600]}") from None
    except urllib.error.URLError as e:
        raise ErrorCH(f"ClickHouse no responde: {e.reason}") from None
    if formato == "JSONEachRow" and not re.search(r"\bFORMAT\s+(?!JSONEachRow)\w+\s*$", sql, re.I):
        return [json.loads(l) for l in texto.splitlines() if l.strip()]
    return texto


# ───────────────────────── extracción anclada a una fecha ─────────────────────────
def anclar(sql: str, corte: date) -> str:
    """Reemplaza now()/today() por la fecha de corte (fin del día, hora Colombia).
    Las consultas ya traen `AND created_at <= now()` en cada ventana, así que con el
    ancla movida quedan acotadas por los dos lados."""
    hasta = f"toDateTime('{corte.isoformat()} 23:59:59', 'America/Bogota')"
    sql = re.sub(r"\bnow\(\)", hasta, sql)
    sql = re.sub(r"\btoday\(\)", f"toDate('{corte.isoformat()}')", sql)
    return sql


def dir_cache(corte: date, base: Path | None = None) -> Path:
    base = base or (Path(os.environ.get("TMPDIR", "/tmp")) / "piloto-score-ch" if os.environ.get("VERCEL") else RAIZ / "data_ch")
    return base / corte.isoformat()


def extraer(corte: date, log=lambda *_: None, forzar: bool = False, base: Path | None = None) -> Path:
    """Deja en dir_cache(corte) los seis CSV. Si ya están (y no se fuerza), no toca la red."""
    destino = dir_cache(corte, base)
    if not forzar and all((destino / salida).exists() for _, salida in EXTRACCION):
        return destino
    destino.mkdir(parents=True, exist_ok=True)
    for archivo, salida in EXTRACCION:
        t0 = time.time()
        sql = anclar((RAIZ / "sql" / archivo).read_text(encoding="utf-8"), corte)
        texto = consultar(sql, formato="CSVWithNames", timeout=600)
        (destino / salida).write_text(texto, encoding="utf-8")
        log(f"{archivo} → {salida}: {max(0, texto.count(chr(10)) - 1)} filas en {time.time() - t0:.1f}s")
    (destino / "_extraido_en.txt").write_text(datetime.now().isoformat(timespec="seconds"))
    return destino


def extraido_en(corte: date, base: Path | None = None) -> str | None:
    f = dir_cache(corte, base) / "_extraido_en.txt"
    return f.read_text().strip() if f.exists() else None


# ───────────────────────── búsqueda (Consulta de Datos) ─────────────────────────
TIPOS_BUSQUEDA = {"id_usuario": "ID de usuario", "documento": "Número de documento", "placa": "Placa",
                  "celular": "Número de celular", "correo": "Correo electrónico"}


def col_placa() -> str | None:
    global _col_placa
    if _col_placa is False:
        forzada = os.environ.get("CONSULTA_DATOS_COL_PLACA", "").strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", forzada):
            _col_placa = forzada
        else:
            cols = [r["name"] for r in consultar(
                "SELECT name FROM system.columns WHERE database = 'picapmongoprod' AND table = 'vehicles' ORDER BY position")]
            bajas = {c.lower(): c for c in cols}
            elegida = next((bajas[c] for c in PLACA_CANDIDATAS if c in bajas), None) or \
                next((c for c in cols if "plate" in c.lower() or "placa" in c.lower()), None)
            _col_placa = elegida if elegida and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", elegida) else None
    return _col_placa


def condicion(tipo: str, valor: str) -> str:
    v = _esc(valor.strip())
    if tipo == "id_usuario":
        return f"toString(p._id) = '{v}'"
    if tipo == "documento":
        return f"trim(toString(pwd.cod_identification)) = '{v}'"
    if tipo == "correo":
        return f"lower(trim(toString(pwd.txt_email))) = '{_esc(valor.strip().lower())}'"
    if tipo == "celular":
        digitos = re.sub(r"\D", "", valor)
        if not digitos:
            raise ValueError("El celular debe tener al menos un dígito")
        return f"replaceRegexpAll(toString(pwd.txt_phone), '[^0-9]', '') = '{digitos}'"
    if tipo == "placa":
        col = col_placa()
        if not col:
            raise ValueError("No se pudo ubicar la columna de placa en vehicles (definí CONSULTA_DATOS_COL_PLACA)")
        placa = _esc(re.sub(r"\s+", "", valor.upper()))
        return (f"toString(p._id) IN (SELECT DISTINCT toString(dve.driver_id) FROM picapmongoprod.driver_vehicle_enrollments dve "
                f"WHERE toString(dve.vehicle_id) IN (SELECT toString(_id) FROM picapmongoprod.vehicles "
                f"WHERE upper(trim(toString({col}))) = '{placa}'))")
    raise ValueError(f"Tipo de búsqueda inválido. Opciones: {', '.join(TIPOS_BUSQUEDA)}")


Q_FICHA = """
SELECT *
FROM (
    SELECT
        formatDateTime(toTimeZone(p.created_at, 'America/Bogota'), '%Y-%m-%d %H:%i') AS creacion_cuenta,
        toString(p._id)                                        AS id_user,
        trim(concat(ifNull(p.name, ''), ' ', ifNull(p.last_name, ''))) AS nombre,
        ifNull(toString(pwd.birth_date), '')                   AS nacimiento,
        ifNull(toString(pwd.cod_identification), '')           AS documento,
        ifNull(toString(pwd.txt_email), '')                    AS correo,
        ifNull(toString(pwd.txt_phone), '')                    AS celular,
        ifNull(toString(p.driver_enrollment_status_cd), '')    AS status_enrollment,
        ifNull(toString(p.is_associated_driver), '')           AS is_associated_driver,
        ifNull(toString(p.is_dedicated_driver), '')            AS is_dedicated_driver,
        ifNull(toString(p.passenger_suspension_comment), '')   AS comentario_user,
        ifNull(toString(p.passenger_expulsion_comment), '')    AS comentario_expulsion_user,
        ifNull(toString(p.driver_suspension_comment), '')      AS comentario_driver,
        ifNull(toString(s.imei), '')                           AS imei,
        ifNull(toString(s.ip_lat), '')                         AS ip_lat,
        ifNull(toString(s.ip_lon), '')                         AS ip_lon,
        ifNull(toString(s.blocked_session), '')                AS blocked_session,
        ifNull(toString(p.is_deactivated), '')                 AS is_deactivated,
        ifNull(toString(p.is_driver_suspended), '')            AS is_driver_suspended,
        ifNull(toString(p.suspended), '')                      AS suspended_user,
        ifNull(toString(p.expelled), '')                       AS status_expelled,
        ifNull(toString(pwd.pssg_photo_url), '')               AS foto_url,
        ifNull(toString(p.rating_as_driver__fl), '')           AS rating_app,
        ROW_NUMBER() OVER (PARTITION BY p._id ORDER BY p._sdc_batched_at DESC) AS rn
    FROM picapmongoprod.passengers p
    LEFT JOIN picapmongoprod.sessions          s   ON p._id = s.passenger_id
    LEFT JOIN picapmongoprod.passengers_w_data pwd ON p._id = pwd._id
    WHERE {condicion}
)
WHERE rn = 1
ORDER BY creacion_cuenta
LIMIT {limite}
"""


def _bool(v) -> bool | None:
    s = str(v or "").strip().lower()
    if not s or s == "null":
        return None
    return s in ("true", "1", "t", "yes", "si", "sí")


def _ficha(f: dict) -> dict:
    return {
        "id_user": f["id_user"], "nombre": f["nombre"], "creacion_cuenta": f["creacion_cuenta"],
        "nacimiento": f["nacimiento"][:10], "documento": f["documento"], "correo": f["correo"], "celular": f["celular"],
        "tipo_cuenta": "Piloto" if f["status_enrollment"] == "3" else "Pasajero",
        "vinculacion": {"asociado": _bool(f["is_associated_driver"]), "dedicado": _bool(f["is_dedicated_driver"])},
        "estado": {"expulsado": _bool(f["status_expelled"]), "suspendido": _bool(f["suspended_user"]),
                   "piloto_suspendido": _bool(f["is_driver_suspended"]), "desactivado": _bool(f["is_deactivated"]),
                   "sesion_bloqueada": _bool(f["blocked_session"])},
        "comentarios_bloqueo": {k: f[k] for k in ("comentario_driver", "comentario_user", "comentario_expulsion_user") if f[k]},
        "imei": f["imei"], "ip": {"lat": f["ip_lat"], "lon": f["ip_lon"]}, "foto_url": f["foto_url"],
        "rating_app": f["rating_app"],
    }


def buscar(tipo: str, valor: str, limite: int = 50) -> list[dict]:
    if not valor.strip():
        raise ValueError("Escribí un valor para buscar")
    if len(valor) > 120:
        raise ValueError("El valor es demasiado largo (máx. 120 caracteres)")
    filas = consultar(Q_FICHA.format(condicion=condicion(tipo, valor), limite=int(limite)), timeout=120)
    return [_ficha(f) for f in filas]


# ───────────────────────── hoja de vida (ficha completa) ─────────────────────────
Q_BLOQUEOS = """
SELECT user_id, countIf(permanente = 0) AS suspensiones, countIf(permanente = 1) AS expulsiones, count() AS total,
       formatDateTime(toTimeZone(max(fecha), 'America/Bogota'), '%Y-%m-%d %H:%i') AS ultimo,
       argMax(detalle, fecha).1 AS ultimo_mensaje, argMax(detalle, fecha).2 AS ultimo_permanente,
       argMax(detalle, fecha).3 AS ultimo_desde,   argMax(detalle, fecha).4 AS ultimo_hasta,
       argMax(detalle, fecha).5 AS ultimo_origen,  argMax(detalle, fecha).6 AS ultimo_vigente,
       argMax(detalle, fecha).7 AS ultimo_tipos
FROM (
    SELECT user_id, suspension_id, max(permanent_flag) AS permanente, max(created) AS fecha,
           argMax((mensaje, permanent_flag, desde, hasta, origen, vigente, tipos), created) AS detalle
    FROM (
        SELECT toString(passenger_id) AS user_id, toString(_id) AS suspension_id, created_at AS created,
               multiIf(lower(ifNull(toString(permanent), '')) IN ('true', '1'), 1, 0) AS permanent_flag,
               ifNull(toString(message), '') AS mensaje,
               parseDateTimeBestEffortOrNull(toString(starts_at)) AS starts_dt,
               if(parseDateTimeBestEffortOrNull(toString(ends_at)) < toDateTime('2100-01-01'),
                  parseDateTimeBestEffortOrNull(toString(ends_at)), NULL) AS ends_dt,
               parseDateTimeBestEffortOrNull(toString(updated_at)) AS updated_dt,
               ifNull(formatDateTime(toTimeZone(starts_dt, 'America/Bogota'), '%Y-%m-%d %H:%i'), '') AS desde,
               ifNull(formatDateTime(toTimeZone(ends_dt,   'America/Bogota'), '%Y-%m-%d %H:%i'), '') AS hasta,
               toUInt8(ifNull(starts_dt IS NOT NULL AND starts_dt <= now() AND (ends_dt IS NULL OR ends_dt >= now())
                       AND (updated_dt IS NULL OR updated_dt <= starts_dt + INTERVAL 5 MINUTE), 0)) AS vigente,
               '' AS tipos, 'USUARIO CONSUMIDOR' AS origen
        FROM picapmongoprod.passenger_suspensions WHERE passenger_id = '{id}'
        UNION ALL
        SELECT toString(driver_id) AS user_id, toString(_id) AS suspension_id, created_at AS created,
               multiIf(ifNull(permanent, false) = true, 1, 0) AS permanent_flag,
               ifNull(toString(message), '') AS mensaje,
               parseDateTimeBestEffortOrNull(toString(starts_at)) AS starts_dt,
               if(parseDateTimeBestEffortOrNull(toString(ends_at)) < toDateTime('2100-01-01'),
                  parseDateTimeBestEffortOrNull(toString(ends_at)), NULL) AS ends_dt,
               parseDateTimeBestEffortOrNull(toString(updated_at)) AS updated_dt,
               ifNull(formatDateTime(toTimeZone(starts_dt, 'America/Bogota'), '%Y-%m-%d %H:%i'), '') AS desde,
               ifNull(formatDateTime(toTimeZone(ends_dt,   'America/Bogota'), '%Y-%m-%d %H:%i'), '') AS hasta,
               toUInt8(ifNull(starts_dt IS NOT NULL AND starts_dt <= now() AND (ends_dt IS NULL OR ends_dt >= now())
                       AND (updated_dt IS NULL OR updated_dt <= starts_dt + INTERVAL 5 MINUTE), 0)) AS vigente,
               ifNull(toString(suspended_service_types), '') AS tipos, 'USUARIO PRESTADOR' AS origen
        FROM picapmongoprod.driver_suspensions WHERE driver_id = '{id}'
    )
    GROUP BY user_id, suspension_id
)
GROUP BY user_id
"""

Q_CONEXION = """
SELECT fecha, lat, lon, app_version, os, modelo
FROM (
    SELECT formatDateTime(toTimeZone(updated_at, 'America/Bogota'), '%Y-%m-%d %H:%i:%S') AS fecha,
           ifNull(toString(lat), '') AS lat, ifNull(toString(lon), '') AS lon,
           ifNull(toString(app_version), '') AS app_version, ifNull(toString(os), '') AS os,
           trim(concat(ifNull(toString(brand), ''), ' ', ifNull(toString(model), ''))) AS modelo,
           ROW_NUMBER() OVER (PARTITION BY passenger_id ORDER BY updated_at DESC) AS rn
    FROM picapmongoprod.sessions
    WHERE passenger_id = '{id}' AND updated_at IS NOT NULL
)
WHERE rn = 1
"""

Q_PLACAS = """
SELECT DISTINCT upper(trim(toString(v.{col}))) AS placa, ifNull(toString(dve.enrollment_status_cd), '') AS estado
FROM picapmongoprod.driver_vehicle_enrollments dve
INNER JOIN picapmongoprod.vehicles v ON toString(v._id) = toString(dve.vehicle_id)
WHERE toString(dve.driver_id) = '{id}' AND notEmpty(upper(trim(toString(v.{col}))))
ORDER BY estado DESC, placa
"""

# Servicios del sujeto como piloto y como usuario, por tipo y estado (mismo criterio de
# tipo que 01_pilotos.sql: con package → mensajería B2B/B2C según company_id; sin → rent).
Q_SERVICIOS = """
WITH
  bk AS (
    SELECT _id,
           argMax(toString(driver_id), _sdc_batched_at)    AS drv,
           argMax(toString(passenger_id), _sdc_batched_at) AS pas,
           argMax(status_cd, _sdc_batched_at)              AS st,
           argMax(toString(company_id), _sdc_batched_at)   AS cia
    FROM picapmongoprod.bookings
    WHERE (toString(driver_id) = '{id}' OR toString(passenger_id) = '{id}') {filtro}
    GROUP BY _id),
  pk AS (SELECT DISTINCT toString(booking_id) AS booking_id FROM picapmongoprod.packages
         WHERE toString(booking_id) IN (SELECT _id FROM bk))
SELECT if(b.drv = '{id}', 'piloto', 'usuario') AS rol,
       if(p.booking_id != '', if(notEmpty(ifNull(b.cia, '')), 'mensajeria_b2b', 'mensajeria_b2c'), 'rent') AS tipo,
       multiIf(b.st IN (4, 107, 108), 'finalizado', b.st = 100, 'cancelado_piloto', b.st = 102, 'cancelado_usuario',
               b.st = 104, 'cancelado_plataforma', b.st = 101, 'expirado', 'otro') AS estado,
       count() AS n
FROM bk b LEFT JOIN pk p ON p.booking_id = b._id
GROUP BY rol, tipo, estado
"""

TIPOS_SERVICIO = ("mensajeria_b2b", "mensajeria_b2c", "rent")
ESTADOS_SERVICIO = ("finalizado", "cancelado_piloto", "cancelado_usuario", "cancelado_plataforma", "expirado", "otro")


def _matriz():
    fila = lambda: {e: 0 for e in ESTADOS_SERVICIO} | {"total": 0}
    return {t: fila() for t in TIPOS_SERVICIO} | {"total": fila()}


def _fecha_sql(s: str | None, hora: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2}))?", s)
    if not m:
        raise ValueError("Fecha inválida (usá AAAA-MM-DD)")
    date.fromisoformat(m.group(1))
    return f"{m.group(1)} {m.group(2) + ':' + m.group(3) + ':00' if m.group(2) else hora}"


def hoja_de_vida(id_user: str, desde: str | None = None, hasta: str | None = None) -> dict:
    """Ficha completa de un sujeto (por id). Los servicios se acotan al rango si viene;
    bloqueos, estado y ficha son SIEMPRE el histórico completo (como en el portal)."""
    if not re.fullmatch(r"[0-9a-fA-F]{24}", id_user or ""):
        raise ValueError("ID de usuario inválido")
    fichas = buscar("id_usuario", id_user, limite=1)
    if not fichas:
        raise ValueError("No existe un usuario con ese ID")
    ficha = fichas[0]
    d, h = _fecha_sql(desde, "00:00:00"), _fecha_sql(hasta, "23:59:59")
    if d and h and d > h:
        raise ValueError("El rango está al revés: 'desde' es posterior a 'hasta'")
    filtro = (f" AND created_at >= toDateTime('{d}', 'America/Bogota')" if d else "") + \
             (f" AND created_at <= toDateTime('{h}', 'America/Bogota')" if h else "")
    if not d and not h:
        filtro = " AND created_at >= now() - INTERVAL 365 DAY"

    b = consultar(Q_BLOQUEOS.format(id=id_user), timeout=60)
    bloqueos = {"suspensiones": 0, "expulsiones": 0, "total": 0, "ultimo": None}
    if b:
        r = b[0]
        bloqueos = {"suspensiones": int(r["suspensiones"]), "expulsiones": int(r["expulsiones"]), "total": int(r["total"]),
                    "ultimo": r["ultimo"], "ultimo_mensaje": r["ultimo_mensaje"], "ultimo_permanente": bool(r["ultimo_permanente"]),
                    "ultimo_desde": r["ultimo_desde"], "ultimo_hasta": r["ultimo_hasta"], "ultimo_origen": r["ultimo_origen"],
                    "ultimo_vigente": bool(r["ultimo_vigente"]), "ultimo_tipos": r["ultimo_tipos"]}
    c = consultar(Q_CONEXION.format(id=id_user), timeout=60)
    conexion = c[0] if c else {"fecha": None, "lat": None, "lon": None, "app_version": None, "os": None, "modelo": None}
    col = col_placa()
    placas = consultar(Q_PLACAS.format(id=id_user, col=col), timeout=60) if col else []
    servicios = {"piloto": _matriz(), "usuario": _matriz()}
    for f in consultar(Q_SERVICIOS.format(id=id_user, filtro=filtro), timeout=120):
        rol, tipo, estado, n = f["rol"], f["tipo"], f["estado"], int(f["n"])
        if rol in servicios and tipo in TIPOS_SERVICIO and estado in ESTADOS_SERVICIO:
            m = servicios[rol]
            m[tipo][estado] += n; m[tipo]["total"] += n; m["total"][estado] += n; m["total"]["total"] += n
    return ficha | {"bloqueos": bloqueos, "ultima_conexion": conexion, "placas": placas, "servicios": servicios,
                    "rango_servicios": {"desde": d, "hasta": h, "por_defecto_365d": not d and not h}}
