# docs/generar_ejemplos.py — imprime en Markdown los ejemplos de data/ con el
# motor real, para pegarlos en METODOLOGIA.md:  python3 docs/generar_ejemplos.py
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from score.engine import evaluar, EVENTOS
from score.io import cargar_config, cargar_datos, RAIZ

HOY = date(2026, 9, 15)
P, W, R = cargar_config()
res = [evaluar(m, P, W, R, HOY) for m in cargar_datos(RAIZ / "data") if m.caso]   # sólo los casos con nombre
f = lambda x: "—" if x is None else f"{x:.1f}"
print("| Piloto | Tipo | Caso | Base | +mejor / −peor | Score | Final | Banda | Vigencia | Estado | Observaciones |")
print("|---|---|---|---:|---:|---:|---:|---|---|---|---|")
for r in res:
    b = r["contribuciones"].get("_bloques") or {}
    est = r["estado"] + (" [" + ",".join(r["restricciones_activas"]) + "]" if r["restricciones_activas"] else "") + (" ⚠ " + ", ".join(r["alertas"]) if r["alertas"] else "")
    print(f"| {r['piloto_id']} | {r['tipo']} | {r['caso']} | {f(b.get('A_base'))} | {'—' if not b else f'+{b.get('ganancia',0):.2f} / −{b.get('perdida',0):.2f}'} | {f(r['score_comportamental'])} | **{f(r['score_final'])}** | {r['banda'] or 'SIN SCORE'} | {r['vigencia']} ({r['confianza']}) | {est} | {'; '.join(r['observaciones']) or '—'} |")

def desglose(pid):
    r = [x for x in res if x["piloto_id"] == pid][0]; b = r["contribuciones"]["_bloques"]
    print(f"\n**{pid} · {r['nombre']} ({r['caso']}) · {r['tipo']}** — base {b['A_base']:.2f} + {b.get('ganancia',0):.2f} − {b.get('perdida',0):.2f} "
          f"= {b.get('score_sin_clip',0):.2f} → **{r['score_final']}** "
          f"({r['banda']}, {r['vigencia']}, estado {r['estado']}"
          + (f", tope por regla {r['tope_por_regla']}" if r['tope_por_regla'] is not None else "") + ")\n")
    print("| Variable | Bloque | Sub-score | Peso efectivo | Aporte (±) | Cálculo |")
    print("|---|---|---:|---:|---:|---|")
    for v, s in r["sub_scores"].items():
        c = r["contribuciones"].get(v)
        if s["score"] is None:
            print(f"| {v} | — | — | — | — | *{s['motivo']}* |"); continue
        det = ", ".join(f"{k}={val}" for k, val in s["detalle"].items() if k != "edades_dias")
        ap = f"{c['aporte']:+.2f}"
        print(f"| {v} | {c['bloque']} | {s['score']:.2f} | {c['peso_efectivo']:.1%} | {ap} | {det} |")

for pid in sys.argv[1:] or ["P005", "P006", "P004"]:
    desglose(pid)
