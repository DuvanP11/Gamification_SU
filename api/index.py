# api/index.py — punto de entrada en Vercel (runtime Python).
# Vercel exige una clase `handler` definida en este archivo (BaseHTTPRequestHandler);
# hereda sin cambios del `H` del afinador local (score/web.py). index.html y static/
# los sirve Vercel como estáticos; vercel.json manda /api/* acá como
# /api/index?ruta=<x>, y H.ruta() reconstruye la ruta original.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from score.web import H  # noqa: E402


class handler(H):  # noqa: N801 — el nombre lo fija Vercel
    pass
