# api/index.py — punto de entrada en Vercel (runtime Python).
# Vercel espera una clase `handler` que herede de BaseHTTPRequestHandler: es el mismo
# `H` del afinador local (score/web.py). index.html y static/ los sirve Vercel como
# archivos estáticos; vercel.json manda todo /api/* acá.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from score.web import H as handler  # noqa: E402,F401
