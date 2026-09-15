# score/cli.py — uso:
#   python3 -m score                       → tabla de todos los pilotos
#   python3 -m score --tipo RENT           → sólo un tipo
#   python3 -m score --explicar P003       → desglose completo de un piloto
#   python3 -m score --json                → salida JSON (para Power BI / pruebas)
#   python3 -m score --hoy 2026-09-15      → fecha de corte (default: hoy)
#   python3 -m score --datos otra/carpeta  → otra fuente de CSV
from __future__ import annotations
import argparse, json, sys
from datetime import date, datetime
from pathlib import Path
from .engine import evaluar, validar_pesos, TIPOS
from .io import cargar_config, cargar_datos, RAIZ


def main(argv=None):
    ap = argparse.ArgumentParser(prog="score", description="Score operacional de pilotos 0.0–5.0")
    ap.add_argument("--tipo", choices=TIPOS)
    ap.add_argument("--explicar", metavar="PILOTO_ID")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hoy", default=None)
    ap.add_argument("--datos", default=str(RAIZ / "data"))
    ap.add_argument("--top", type=int, metavar="N", help="mostrar los N mejores, N del medio y N peores")
    a = ap.parse_args(argv)
    hoy = datetime.strptime(a.hoy, "%Y-%m-%d").date() if a.hoy else date.today()

    params, pesos, reglas = cargar_config()
    for t in TIPOS:
        for av in validar_pesos(pesos.get(t, {}), params["general"]["max_participacion_peso"]):
            print(f"⚠️  pesos[{t}]: {av}", file=sys.stderr)
    datos = cargar_datos(Path(a.datos))
    if a.tipo:
        datos = [m for m in datos if m.tipo == a.tipo]
    if a.explicar:
        datos = [m for m in datos if m.piloto_id == a.explicar]
        if not datos:
            sys.exit(f"no existe el piloto {a.explicar}")
    res = [evaluar(m, params, pesos, reglas, hoy) for m in datos]

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str)); return
    if a.explicar:
        for r in res:
            explicar(r)
        return
    if a.top:
        con = sorted([r for r in res if r["score_final"] is not None], key=lambda r: (-r["score_final"], -r["n_aplicables"]))
        N = a.top; c = len(con) // 2; ini = max(N, min(c - N // 2, len(con) - 2 * N))
        for titulo, grupo, off in ((f"TOP {N} MEJORES", con[:N], 0), (f"{N} DEL MEDIO", con[ini:ini + N] if len(con) > 2 * N else [], ini),
                                   (f"{N} PEORES", con[max(N, len(con) - N):] if len(con) > N else [], max(N, len(con) - N))):
            if not grupo: continue
            print(f"\n── {titulo} ──")
            print(f"{'#':>3} {'nombre':24} {'tipo':5} {'id piloto':24} {'id pasajero':24} {'act.piloto':10} {'act.pasaj.':10} {'gamif':>5} {'app':>4} {'final':>5} {'banda':12}  observaciones")
            for i, r in enumerate(grupo):
                obs = "; ".join(r["observaciones"]) or "—"
                g = "—" if r["calif_gamification"] is None else f"{r['calif_gamification']:.1f}"
                ap_ = "—" if r["calif_app"] is None else f"{r['calif_app']:.1f}"
                print(f"{off+i+1:>3} {r['nombre'][:24]:24} {r['tipo']:5} {r['driver_id']:24} {r['passenger_id']:24} {(r['activado_piloto'] or '—'):10} {(r['activado_pasajero'] or '—'):10} {g:>5} {ap_:>4} {r['score_final']:>5.1f} {r['banda'][:12]:12}  {obs}")
        return
    print(f"{'piloto':8} {'tipo':5} {'nombre':22} {'score':>5} {'final':>5} {'banda':22} {'vig.':12} {'conf':>4} {'n':>4}  estado / alertas / observaciones")
    for r in res:
        sc = "—" if r["score_comportamental"] is None else f"{r['score_comportamental']:.1f}"
        sf = "—" if r["score_final"] is None else f"{r['score_final']:.1f}"
        extra = r["estado"]
        if r["restricciones_activas"]: extra += " [" + ",".join(r["restricciones_activas"]) + "]"
        if r["alertas"]: extra += " ⚠ " + ",".join(r["alertas"])
        if r["observaciones"]: extra += "  · " + "; ".join(r["observaciones"])
        print(f"{r['piloto_id']:8} {r['tipo']:5} {r['nombre'][:22]:22} {sc:>5} {sf:>5} {str(r['banda']):22} {r['vigencia']:12} {r['confianza']:>4.2f} {r['n_aplicables']:>4}  {extra}")


def explicar(r: dict):
    print(f"\n═══ {r['piloto_id']} · {r['nombre']} · {r['tipo']} ═══")
    print(f"score comportamental: {r['score_comportamental']}   score final: {r['score_final']}   banda: {r['banda']}")
    print(f"vigencia: {r['vigencia']} (n={r['n_aplicables']}, n_min={r['n_min']}, confianza={r['confianza']})   estado: {r['estado']}")
    if r["restricciones_activas"]: print(f"restricciones activas: {', '.join(r['restricciones_activas'])}")
    dc = r.get("documentos") or {}
    if dc.get("detalle"):
        d = dc["detalle"]
        print(f"documentos: licencia {d['licencia']} | policía {d['policia']} | SOAT {d['soat_vence'] or 'sin dato'} | tecno {d['tecno_vence'] or 'sin dato'}")
        for x in dc["restringe"]: print(f"  ⛔ {x}")
        for x in dc["alertas"]: print(f"  ⚠ {x}")
        for x in dc["por_vencer"]: print(f"  ⏳ {x}")
    if r["alertas"]: print(f"reglas: {', '.join(r['alertas'])}" + (f"  → tope {r['tope_por_regla']}" if r["tope_por_regla"] is not None else ""))
    b = r["contribuciones"].get("_bloques")
    if b:
        print(f"D (confianza ganada) = {b['D_base']:.3f}   P (penalizaciones) = {b['P_penal']:.3f}   "
              f"factor = 1 − {b['alpha']}·P = {b['factor']:.3f}   →  D·factor = {b['D_base']*b['factor']:.3f}")
    print(f"\n{'variable':24} {'bloque':13} {'sub':>6} {'peso ef.':>9} {'aporte/desc.':>12}  detalle")
    for var, s in r["sub_scores"].items():
        c = r["contribuciones"].get(var)
        if s["score"] is None:
            print(f"{var:24} {'—':13} {'—':>6} {'—':>9} {'—':>12}  ({s['motivo']})"); continue
        det = ", ".join(f"{k}={v}" for k, v in s["detalle"].items() if k != "edades_dias")
        if not c:
            print(f"{var:24} {'(peso 0)':13} {s['score']:>6.2f} {'0%':>9} {'0':>12}  {det}"); continue
        pe = f"{c['peso_efectivo']:.1%}"
        ap = f"+{c['aporte']:.2f}" if c["bloque"] == "positiva" else f"−{c['descuento']:.1%}"
        print(f"{var:24} {c['bloque']:13} {s['score']:>6.2f} {pe:>9} {ap:>12}  {det}")
