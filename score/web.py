# score/web.py — afinador: python3 -m score.web  → http://127.0.0.1:8765
# Sin dependencias: http.server + index.html. Recalcula con los parámetros que se
# editan en pantalla (sin tocar disco); los pesos son definitivos (config/pesos.yaml).
# El mismo handler `H` corre en Vercel como función serverless (api/index.py): ahí
# index.html y static/ los sirve Vercel como estáticos y sólo /api/* llega acá.
from __future__ import annotations
import json, os, sys, webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import yaml
from .engine import evaluar, validar_pesos, TIPOS, EVENTOS
from .io import cargar_config, cargar_datos, fuentes_de_datos, RAIZ
from . import ch

PUERTO = 8765
HTML = (RAIZ / "index.html").read_text(encoding="utf-8")
EN_VERCEL = bool(os.environ.get("VERCEL"))
# Clave de acceso a la web. Obligatoria cuando está publicada: la ficha trae datos
# personales de pilotos. En local, sin APP_PASSWORD, no se pide nada.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
FUENTE_CH = "clickhouse"
_CACHE: dict = {}   # clave de fuente → (firma mtimes, datos)
_LOG_EXTRACCION: list[str] = []

CAMPOS_FILA = ("piloto_id", "nombre", "caso", "tipo", "driver_id", "passenger_id", "activado_piloto",
               "activado_pasajero", "ultimo_servicio", "calif_gamification", "gamif_puntos", "gamif_final", "calif_app",
               "score_comportamental", "score_final", "banda", "vigencia", "confianza", "n_aplicables",
               "n_min", "estado", "restricciones_activas", "tope_por_regla", "alertas", "observaciones", "documentos", "cupo")


def fuentes() -> list[str]:
    """CSV locales (data*, con pilotos.csv) + ClickHouse en vivo si hay credenciales."""
    return fuentes_de_datos() + ([FUENTE_CH] if ch.configurado() else [])


def directorio_fuente(fuente: str, corte: date) -> Path:
    """Dónde están los CSV de esa fuente. Para ClickHouse: la extracción anclada al corte
    (se corre la primera vez que se pide esa fecha; después queda en caché en disco)."""
    if fuente == FUENTE_CH:
        _LOG_EXTRACCION.clear()
        return ch.extraer(corte, log=_LOG_EXTRACCION.append)
    return RAIZ / fuente


def datos_cacheados(fuente: str, corte: date):
    d = directorio_fuente(fuente, corte)
    firma = tuple((f.name, f.stat().st_mtime) for f in sorted(d.glob("*.csv")))
    clave = f"{fuente}@{corte.isoformat()}" if fuente == FUENTE_CH else fuente
    if _CACHE.get(clave, (None,))[0] != firma:
        _CACHE[clave] = (firma, cargar_datos(d))
    return _CACHE[clave][1]


def resumen_score(r: dict) -> dict:
    """Lo que el buscador muestra de cada tipo: score, banda, estado, cupo y observaciones."""
    return {k: r.get(k) for k in ("tipo", "score_final", "banda", "vigencia", "confianza", "n_aplicables", "n_min",
                                  "estado", "alertas", "observaciones", "cupo", "piloto_id")}


def fila(r: dict) -> dict:
    return {k: r.get(k) for k in CAMPOS_FILA}


def ranking(res: list[dict], n: int, solo_definitivos: bool) -> dict:
    """top n / n del medio / n peores por tipo, más conteos."""
    out = {}
    for tipo in TIPOS:
        rs = [r for r in res if r["tipo"] == tipo]
        con = [r for r in rs if r["score_final"] is not None and (not solo_definitivos or r["vigencia"] == "DEFINITIVO")]
        con.sort(key=lambda r: (-r["score_final"], -r["n_aplicables"]))
        top = con[:n]
        peores = con[max(n, len(con) - n):] if len(con) > n else []
        medio, ini = [], 0
        if len(con) > 2 * n:
            c = len(con) // 2; ini = max(n, min(c - n // 2, len(con) - 2 * n)); medio = con[ini:ini + n]
        out[tipo] = {"top": [fila(r) for r in top], "medio": [fila(r) for r in medio], "medio_desde": ini,
                     "peores": [fila(r) for r in peores], "peores_desde": len(con) - len(peores),
                     "n_ranking": len(con), "n_total": len(rs),
                     "n_sin_score": sum(1 for r in rs if r["score_final"] is None),
                     "n_provisional": sum(1 for r in rs if r["vigencia"] == "PROVISIONAL"),
                     "bandas": dict(sorted(__import__("collections").Counter(r["banda"] for r in con).items()))}
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    # En Vercel el rewrite manda /api/<x> a /api/index?ruta=<x>: si llega así, se
    # reconstruye la ruta original. En local (y si Vercel conserva el path) no cambia nada.
    def ruta(self) -> str:
        p, _, q = self.path.partition("?")
        if p.rstrip("/") in ("/api/index", "/api") and "ruta=" in q:
            from urllib.parse import parse_qs
            r = parse_qs(q).get("ruta", [""])[0]
            return "/api/" + r if r else "/api"
        return p

    def autorizado(self) -> bool:
        """Con APP_PASSWORD definida, todo /api/* exige la cabecera X-Clave."""
        if not APP_PASSWORD or not self.path.startswith("/api/"):
            return True
        if self.headers.get("X-Clave", "") == APP_PASSWORD:
            return True
        self._json({"ok": False, "error": "clave requerida", "auth": True}, 401)
        return False

    def do_GET(self):
        self.path = self.ruta()
        if not self.autorizado():
            return
        if self.path == "/":
            b = HTML.encode(); self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        ruta = self.path
        if ruta.startswith("/static/") and ruta.endswith((".png", ".ico")) and "/" not in ruta[8:]:
            f = RAIZ / "static" / ruta[8:]
            if f.exists():
                b = f.read_bytes(); self.send_response(200)
                self.send_header("Content-Type", "image/png" if ruta.endswith(".png") else "image/x-icon"); self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "max-age=86400"); self.end_headers(); self.wfile.write(b); return
        if self.path == "/api/config":
            p, w, r = cargar_config()
            self._json({"parametros": p, "pesos": w, "reglas": r,
                        "parametros_yaml": (RAIZ / "config/parametros.yaml").read_text(encoding="utf-8"),
                        "hoy": date.today().isoformat(), "fuentes": fuentes(), "fuente_ch": FUENTE_CH,
                        "clickhouse": ch.configurado(), "tipos_busqueda": ch.TIPOS_BUSQUEDA,
                        "con_clave": bool(APP_PASSWORD), "en_vercel": EN_VERCEL}); return
        self.send_response(404); self.end_headers()

    def contexto(self, body: dict):
        """Parámetros, pesos, reglas, fecha de corte y datos que piden score/detalle/buscar."""
        params = yaml.safe_load(body["parametros_yaml"]) if body.get("parametros_yaml") else cargar_config()[0]
        # Pesos DEFINITIVOS (2026-09-16): se leen siempre de config/pesos.yaml; lo que
        # mande el navegador se ignora, para que nadie los mueva desde el afinador.
        _, pesos, reglas = cargar_config()
        hoy = datetime.strptime(body.get("hoy") or date.today().isoformat(), "%Y-%m-%d").date()
        fuente = body.get("datos") or "data"
        if fuente not in fuentes():
            raise ValueError(f"fuente de datos desconocida: {fuente}")
        return params, pesos, reglas, hoy, fuente, datos_cacheados(fuente, hoy)

    def do_POST(self):
        self.path = self.ruta()
        if not self.autorizado():
            return
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path in ("/api/score", "/api/detalle", "/api/buscar"):
            try:
                params, pesos, reglas, hoy, fuente, datos = self.contexto(body)
                if self.path == "/api/detalle":
                    m = next((m for m in datos if m.piloto_id == body["piloto_id"] and m.tipo == body["tipo"]), None)
                    if m is None:
                        raise ValueError("piloto no encontrado")
                    self._json({"ok": True, "detalle": evaluar(m, params, pesos, reglas, hoy), "parametros": params}); return
                if self.path == "/api/buscar":
                    # Quién es (ClickHouse en vivo) + su score en la fuente/corte elegidos.
                    tipo, valor = str(body.get("tipo") or ""), str(body.get("valor") or "")
                    if not ch.configurado():
                        raise ValueError("la búsqueda por cédula/placa/celular/correo necesita ClickHouse (CH_PASSWORD)")
                    fichas = ch.buscar(tipo, valor)
                    resultados = []
                    for f in fichas:
                        ms = [m for m in datos if m.piloto_id == f["id_user"] or m.driver_id == f["id_user"]]
                        resultados.append(f | {"scores": [resumen_score(evaluar(m, params, pesos, reglas, hoy)) for m in ms]})
                    self._json({"ok": True, "tipo": tipo, "valor": valor, "resultados": resultados, "fuente": fuente,
                                "hoy": hoy.isoformat()}); return
                avisos = {t: validar_pesos(pesos.get(t, {}), params["general"]["max_participacion_peso"]) for t in TIPOS}
                res = [evaluar(m, params, pesos, reglas, hoy) for m in datos]
                self._json({"ok": True, "ranking": ranking(res, int(body.get("n") or 10), bool(body.get("solo_definitivos", True))),
                            "avisos": avisos, "parametros": params, "n_filas": len(res), "fuente": fuente,
                            "extraido_en": ch.extraido_en(hoy) if fuente == FUENTE_CH else None,
                            "log_extraccion": list(_LOG_EXTRACCION) if fuente == FUENTE_CH else []})
            except Exception as e:
                self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)
            return
        if self.path == "/api/hoja":
            try:
                if not ch.configurado():
                    raise ValueError("la hoja de vida necesita ClickHouse (CH_PASSWORD)")
                self._json({"ok": True, "hoja": ch.hoja_de_vida(str(body.get("id_user") or ""), body.get("desde"), body.get("hasta"))})
            except Exception as e:
                self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)
            return
        if self.path == "/api/extraer":
            # Vuelve a bajar de ClickHouse los CSV del corte (por defecto hoy), aunque ya estén en caché.
            try:
                if not ch.configurado():
                    raise ValueError("ClickHouse no está configurado (CH_PASSWORD)")
                hoy = datetime.strptime(body.get("hoy") or date.today().isoformat(), "%Y-%m-%d").date()
                _LOG_EXTRACCION.clear()
                d = ch.extraer(hoy, log=_LOG_EXTRACCION.append, forzar=True)
                _CACHE.pop(f"{FUENTE_CH}@{hoy.isoformat()}", None)
                self._json({"ok": True, "directorio": str(d), "log": list(_LOG_EXTRACCION), "extraido_en": ch.extraido_en(hoy)})
            except Exception as e:
                self._json({"ok": False, "error": f"{type(e).__name__}: {e}", "log": list(_LOG_EXTRACCION)}, 400)
            return
        if self.path == "/api/guardar":
            try:
                if EN_VERCEL:
                    raise PermissionError("en producción no se guarda: los parámetros se cambian en el repo (config/parametros.yaml) y se despliegan")
                if "pesos" in body:
                    raise PermissionError("los pesos son definitivos (2026-09-16); se cambian sólo a mano en config/pesos.yaml")
                if "parametros_yaml" in body:
                    yaml.safe_load(body["parametros_yaml"])  # valida antes de escribir
                    (RAIZ / "config/parametros.yaml").write_text(body["parametros_yaml"], encoding="utf-8")
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)
            return
        self.send_response(404); self.end_headers()


def main():
    # Sólo un entero cuenta como puerto; cualquier otra cosa (p. ej. un "#" de
    # un comentario que la shell no filtró) se ignora.
    puerto = next((int(a) for a in sys.argv[1:] if a.isdigit()), PUERTO)
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), H)
    url = f"http://127.0.0.1:{puerto}"
    print(f"Afinador de score en {url}  (Ctrl+C para salir)")
    print("ClickHouse en vivo: " + ("ACTIVO (CH_PASSWORD definida)" if ch.configurado() else "apagado — exportá CH_PASSWORD para activarlo"))
    print("Clave de acceso: " + ("ACTIVA" if APP_PASSWORD else "sin clave (sólo local)"))
    try: webbrowser.open(url)
    except Exception: pass
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
