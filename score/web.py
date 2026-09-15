# score/web.py — afinador local: python3 -m score.web  → http://127.0.0.1:8765
# Sin dependencias: http.server + una página con sliders. Recalcula con los
# pesos/parámetros que se editan en pantalla (sin tocar disco) y permite
# guardar pesos.yaml / parametros.yaml cuando el ajuste convence.
from __future__ import annotations
import json, sys, webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import yaml
from .engine import evaluar, validar_pesos, TIPOS, EVENTOS
from .io import cargar_config, cargar_datos, RAIZ

PUERTO = 8765
HTML = (Path(__file__).parent / "web.html").read_text(encoding="utf-8")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/":
            b = HTML.encode(); self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if self.path == "/api/config":
            p, w, r = cargar_config()
            self._json({"parametros": p, "pesos": w, "reglas": r,
                        "parametros_yaml": (RAIZ / "config/parametros.yaml").read_text(encoding="utf-8"),
                        "hoy": date.today().isoformat()}); return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/score":
            try:
                params = yaml.safe_load(body["parametros_yaml"]) if body.get("parametros_yaml") else cargar_config()[0]
                pesos, reglas = body["pesos"], cargar_config()[2]
                hoy = datetime.strptime(body.get("hoy") or date.today().isoformat(), "%Y-%m-%d").date()
                datos = cargar_datos(Path(body.get("datos") or RAIZ / "data"))
                avisos = {t: validar_pesos(pesos.get(t, {}), params["general"]["max_participacion_peso"]) for t in TIPOS}
                res = [evaluar(m, params, pesos, reglas, hoy) for m in datos]
                self._json({"ok": True, "resultados": res, "avisos": avisos, "parametros": params})
            except Exception as e:
                self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)
            return
        if self.path == "/api/guardar":
            try:
                if "pesos" in body:
                    (RAIZ / "config/pesos.yaml").write_text(
                        "# Guardado desde el afinador local (" + datetime.now().isoformat(timespec='seconds') + ")\n"
                        + yaml.safe_dump(body["pesos"], sort_keys=False, allow_unicode=True), encoding="utf-8")
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
    try: webbrowser.open(url)
    except Exception: pass
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
