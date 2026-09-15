# score/engine.py — motor del Score Operacional de Pilotos.
#
# Funciones PURAS: reciben datos ya agregados + parámetros y devuelven un
# resultado explicable. Cada primitiva tiene su equivalente directo en SQL,
# Excel/DAX o Python, y la metodología (docs/METODOLOGIA.md) las cita por nombre.
#
# Capas:
#   1. sub_scores      : una función por variable, cada una devuelve 0–5 o None
#                        (None = no aplica / sin dato → sale del cálculo).
#   2. score_comportamental : promedio ponderado de los sub-scores presentes.
#   3. reglas          : gate de riesgo (bloqueo / tope / alerta), nunca puntos.
#   4. resultado       : score, banda, confianza, estado y desglose.
from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import date

TIPOS = ("B2B", "RENT", "B2C")

EVENTOS = ("suspension_piloto", "suspension_pasajero", "invitacion_pibox",
           "invitacion_rent", "expulsion", "baneo_imei", "bloqueo_24h")


# ────────────────────────────── primitivas ──────────────────────────────
def clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def rampa(x: float, x_score0: float, x_score5: float, score_max: float = 5.0) -> float:
    """Lineal entre (x_score0 → 0) y (x_score5 → score_max), recortada.
    Sirve en las dos direcciones: si x_score0 > x_score5, "menos es mejor".
    SQL: score_max * least(1, greatest(0, (x - x0) / (x5 - x0)))"""
    if x_score5 == x_score0:
        raise ValueError("rampa: x_score0 y x_score5 no pueden ser iguales")
    return score_max * clip((x - x_score0) / (x_score5 - x_score0), 0.0, 1.0)


def tasa_ajustada(x: float, n: float, p0: float, m: float) -> float:
    """Suavizado bayesiano (Beta-Binomial / Laplace generalizado):
    (x + m·p0) / (n + m). Con n=0 devuelve p0; con n≫m converge a x/n."""
    if n < 0 or x < 0 or x > n:
        raise ValueError(f"tasa_ajustada: x={x} n={n} inválidos")
    return (x + m * p0) / (n + m)


def decaimiento(edad_dias: float, semivida_dias: float) -> float:
    """Peso de un evento según su antigüedad: 0.5^(edad/semivida).
    Hoy = 1.0; a una semivida = 0.5; a dos = 0.25. SQL: pow(0.5, edad/semivida)."""
    if edad_dias < 0:
        edad_dias = 0.0
    return 0.5 ** (edad_dias / semivida_dias)


def carga_eventos(edades_dias: list[float], semivida_dias: float, severidad: float = 1.0,
                  ventana_dias: float | None = None) -> float:
    """Σ severidad · decaimiento(edad). Eventos fuera de la ventana no cuentan."""
    total = 0.0
    for e in edades_dias:
        if ventana_dias is not None and e > ventana_dias:
            continue
        total += severidad * decaimiento(e, semivida_dias)
    return total


def sub_score_evento(carga: float, tope: float, score_max: float = 5.0) -> float:
    """5 · (1 − min(1, carga/tope)). carga=0 → 5; carga≥tope → 0."""
    return score_max * (1.0 - clip(carga / tope, 0.0, 1.0))


def sub_score_volumen(n: int, n_ref: int, score_max: float = 5.0) -> float:
    """Experiencia saturante: 5·min(1, ln(1+n)/ln(1+n_ref)). El primer tramo
    vale mucho, después de n_ref ya no suma (no premia volumen infinito)."""
    if n <= 0:
        return 0.0
    return score_max * clip(math.log1p(n) / math.log1p(n_ref), 0.0, 1.0)


# ────────────────────────────── entradas ──────────────────────────────
@dataclass
class Evento:
    tipo: str            # uno de EVENTOS
    fecha: date
    activo: bool = False # vigente hoy (restringe si el tipo lo indica)
    severidad: float | None = None  # override puntual; None = la del parámetro


@dataclass
class Metricas:
    """Agregados del piloto para UN tipo de servicio en la ventana de tasas.
    None = dato no disponible (≠ 0). Los conteos de reservas / alto valor /
    novedades sólo tienen sentido en los tipos donde aplican."""
    piloto_id: str
    tipo: str
    nombre: str = ""
    dias_antiguedad: int | None = None
    n_finalizados: int = 0
    n_cancel_piloto: int = 0
    n_cancel_pasajero: int = 0        # no atribuible: sale del denominador
    n_cancel_plataforma: int = 0      # no atribuible
    n_otros_atribuibles: int = 0      # no-show, abandono, etc. (atribuibles ≠ cancelación)
    # sin novedades (B2B/B2C): sobre finalizados
    n_sin_novedad_a_tiempo: int | None = None
    # alto valor (B2B/B2C)
    n_alto_valor: int | None = None
    n_alto_valor_ok: int | None = None
    # reservas (B2B)
    n_res_cumplidas: int | None = None
    n_res_incumplidas_atrib: int | None = None
    n_res_cancel_atrib: int | None = None
    n_res_no_atrib: int | None = None  # informativo: NO entra al denominador
    eventos: list[Evento] = field(default_factory=list)
    reglas_activas: list[str] = field(default_factory=list)

    @property
    def n_aplicables(self) -> int:
        """Servicios cuyo desenlace dependió del piloto."""
        return self.n_finalizados + self.n_cancel_piloto + self.n_otros_atribuibles

    @property
    def n_totales(self) -> int:
        return self.n_aplicables + self.n_cancel_pasajero + self.n_cancel_plataforma


# ────────────────────────────── sub-scores ──────────────────────────────
def _p(params, *ruta, tipo=None):
    v = params
    for k in ruta:
        v = v[k]
    if isinstance(v, dict) and tipo is not None and tipo in v:
        return v[tipo]
    return v


def sub_scores(m: Metricas, params: dict, hoy: date) -> dict[str, dict]:
    """Devuelve {variable: {"score": 0–5 | None, "detalle": {...}}} para TODAS
    las variables del modelo; las no aplicables al tipo van con score None y
    motivo 'no_aplica', las sin dato con motivo 'sin_dato'."""
    g = params["general"]
    smax = g["score_max"]
    out: dict[str, dict] = {}
    aplica = params["aplicabilidad"]

    def no(var, motivo):
        out[var] = {"score": None, "motivo": motivo}

    # 1) Eventos negativos: carga con decaimiento
    for var in EVENTOS:
        if m.tipo not in aplica[var]:
            no(var, "no_aplica"); continue
        cfg = params["eventos"][var]
        evs = [e for e in m.eventos if e.tipo == var]
        edades, carga = [], 0.0
        for e in evs:
            edad = (hoy - e.fecha).days
            if edad > g["ventana_eventos_dias"]:
                continue
            sev = cfg["severidad"] if e.severidad is None else e.severidad
            edades.append(edad)
            carga += sev * decaimiento(edad, cfg["semivida_dias"])
        s = sub_score_evento(carga, cfg["tope"], smax)
        out[var] = {"score": s, "detalle": {"n_eventos": len(evs), "en_ventana": len(edades),
                                            "carga": round(carga, 3), "tope": cfg["tope"],
                                            "edades_dias": edades}}

    # 2) Cancelación propia (tasa, menos es mejor)
    var = "cancelacion_piloto"
    if m.tipo not in aplica[var]:
        no(var, "no_aplica")
    elif m.n_aplicables == 0:
        no(var, "sin_dato")
    else:
        c = params["tasas"][var]
        cruda = m.n_cancel_piloto / m.n_aplicables
        adj = tasa_ajustada(m.n_cancel_piloto, m.n_aplicables, c["p0"], c["m"])
        out[var] = {"score": rampa(adj, c["x_score0"], c["x_score5"], smax),
                    "detalle": {"x": m.n_cancel_piloto, "n": m.n_aplicables,
                                "tasa_cruda": round(cruda, 4), "tasa_ajustada": round(adj, 4),
                                "excluidos_no_atribuibles": m.n_cancel_pasajero + m.n_cancel_plataforma}}

    # 3) Finalizados: volumen / experiencia (saturante)
    var = "finalizados"
    if m.tipo not in aplica[var]:
        no(var, "no_aplica")
    elif m.n_aplicables == 0:
        no(var, "sin_dato")   # 0 servicios ≠ "0 de experiencia": sin evidencia
    else:
        n_ref = _p(params, "volumen", "finalizados", "n_ref", tipo=m.tipo)
        tasa_fin = (m.n_finalizados / m.n_aplicables) if m.n_aplicables else None
        out[var] = {"score": sub_score_volumen(m.n_finalizados, n_ref, smax),
                    "detalle": {"n": m.n_finalizados, "n_ref": n_ref,
                                "tasa_finalizacion": None if tasa_fin is None else round(tasa_fin, 4)}}

    # 4) Sin novedades dentro de tiempos (tasa sobre finalizados)
    var = "sin_novedades"
    if m.tipo not in aplica[var]:
        no(var, "no_aplica")
    elif m.n_sin_novedad_a_tiempo is None or m.n_finalizados == 0:
        no(var, "sin_dato")
    else:
        c = params["tasas"][var]
        x, n = m.n_sin_novedad_a_tiempo, m.n_finalizados
        adj = tasa_ajustada(x, n, c["p0"], c["m"])
        out[var] = {"score": rampa(adj, c["x_score0"], c["x_score5"], smax),
                    "detalle": {"x": x, "n": n, "tasa_cruda": round(x / n, 4), "tasa_ajustada": round(adj, 4)}}

    # 5) Alto valor declarado (mixta: exposición × desempeño)
    var = "alto_valor"
    if m.tipo not in aplica[var]:
        no(var, "no_aplica")
    elif not m.n_alto_valor or m.n_alto_valor_ok is None or m.n_finalizados == 0:
        no(var, "sin_dato")
    else:
        c = params["tasas"][var]
        n_av, ok = m.n_alto_valor, m.n_alto_valor_ok
        prop = n_av / m.n_finalizados
        expo = math.sqrt(clip(n_av / c["n_ref"], 0, 1) * clip(prop / c["prop_ref"], 0, 1))
        adj = tasa_ajustada(ok, n_av, c["p0"], c["m"])
        s_neutro = rampa(c["p0"], c["x_score0"], c["x_score5"], smax)
        s_desemp = rampa(adj, c["x_score0"], c["x_score5"], smax)
        s = s_neutro + expo * (s_desemp - s_neutro)
        out[var] = {"score": s, "detalle": {"n_alto_valor": n_av, "ok": ok, "proporcion": round(prop, 4),
                                            "exposicion": round(expo, 4), "cumplimiento_ajustado": round(adj, 4),
                                            "score_neutro": round(s_neutro, 3), "score_desempeno": round(s_desemp, 3)}}

    # 6) Cumplimiento de reservas (B2B)
    var = "cumplimiento_reservas"
    if m.tipo not in aplica[var]:
        no(var, "no_aplica")
    else:
        cum = m.n_res_cumplidas or 0
        inc = (m.n_res_incumplidas_atrib or 0) + (m.n_res_cancel_atrib or 0)
        n = cum + inc
        if m.n_res_cumplidas is None or n == 0:
            no(var, "sin_dato")
        else:
            c = params["tasas"][var]
            adj = tasa_ajustada(cum, n, c["p0"], c["m"])
            out[var] = {"score": rampa(adj, c["x_score0"], c["x_score5"], smax),
                        "detalle": {"cumplidas": cum, "incumplidas_atrib": inc, "n": n,
                                    "no_atribuibles_excluidas": m.n_res_no_atrib or 0,
                                    "tasa_cruda": round(cum / n, 4), "tasa_ajustada": round(adj, 4)}}
    return out


# ────────────────────────────── agregación ──────────────────────────────
def validar_pesos(pesos_tipo: dict[str, float], max_participacion: float) -> list[str]:
    avisos = []
    total = sum(v for v in pesos_tipo.values() if v)
    if total <= 0:
        avisos.append("la suma de pesos es 0")
        return avisos
    for k, v in pesos_tipo.items():
        if v < 0:
            avisos.append(f"peso negativo en {k}")
        elif v / total > max_participacion:
            avisos.append(f"{k} concentra {v/total:.0%} > {max_participacion:.0%} permitido")
    return avisos


def _promedio_ponderado(subs: dict[str, dict], pesos_tipo: dict[str, float], vars_: tuple[str, ...]):
    num = den = 0.0
    for var in vars_:
        r = subs.get(var)
        if not r or r.get("score") is None:
            continue
        w = pesos_tipo.get(var, 0) or 0
        if w <= 0:
            continue
        num += w * r["score"]; den += w
    return (num / den if den else None), den


def score_comportamental(subs: dict[str, dict], pesos_tipo: dict[str, float],
                         alpha: float = 1.0, score_max: float = 5.0) -> tuple[float | None, dict]:
    """Dos bloques:
      D = Σ w·s / Σ w   sobre las variables de DESEMPEÑO con dato (renormaliza).
      P = Σ w_e·(1 − s_e/5) / Σ w_e   sobre las variables de ANTECEDENTES (0 = limpio, 1 = todo al tope).
      SCORE = D · (1 − α·P)
    Un historial limpio NO suma puntos (P=0 → SCORE=D); uno cargado descuenta
    como máximo α·(w_e/Σw_e) por variable, así ninguna domina sola.
    Si no hay ninguna variable de desempeño con dato → None (sin evidencia)."""
    desemp = tuple(v for v in subs if v not in EVENTOS)
    D, den_d = _promedio_ponderado(subs, pesos_tipo, desemp)
    if D is None:
        return None, {}
    contrib = {}
    for var in desemp:
        r = subs[var]; w = pesos_tipo.get(var, 0) or 0
        if r.get("score") is not None and w > 0:
            contrib[var] = {"bloque": "desempeno", "peso_efectivo": w / den_d, "aporte": w / den_d * r["score"]}
    num_p = den_p = 0.0
    for var in EVENTOS:
        r = subs.get(var); w = pesos_tipo.get(var, 0) or 0
        if not r or r.get("score") is None or w <= 0:
            continue
        num_p += w * (1.0 - r["score"] / score_max); den_p += w
    P = (num_p / den_p) if den_p else 0.0
    for var in EVENTOS:
        r = subs.get(var); w = pesos_tipo.get(var, 0) or 0
        if r and r.get("score") is not None and w > 0:
            contrib[var] = {"bloque": "antecedentes", "peso_efectivo": w / den_p,
                            "descuento": alpha * w / den_p * (1.0 - r["score"] / score_max)}
    contrib["_bloques"] = {"D_desempeno": D, "P_antecedentes": P, "factor": 1.0 - alpha * P, "alpha": alpha}
    return D * (1.0 - alpha * P), contrib


def aplicar_reglas(score: float | None, reglas_activas: list[str], catalogo: dict) -> dict:
    estado, tope_aplicado, alertas = "OK", None, []
    score_final = score
    for r in reglas_activas:
        cfg = catalogo.get(r)
        if not cfg:
            alertas.append(f"{r} (regla no catalogada)"); continue
        ef = cfg.get("efecto", "alerta")
        if ef == "bloqueo":
            estado = "BLOQUEADO"; alertas.append(r)
        elif ef == "tope":
            t = float(cfg["tope"])
            if score_final is not None and score_final > t:
                score_final = t
                tope_aplicado = min(t, tope_aplicado) if tope_aplicado is not None else t
            alertas.append(r)
        else:
            alertas.append(r)
    return {"estado": estado, "score_final": score_final, "tope": tope_aplicado, "alertas": alertas}


def banda(score: float | None, bandas: list[dict]) -> str | None:
    if score is None:
        return None
    for b in sorted(bandas, key=lambda b: -b["desde"]):
        if score >= b["desde"]:
            return b["nombre"]
    return bandas[-1]["nombre"]


def evaluar(m: Metricas, params: dict, pesos: dict, reglas: dict, hoy: date | None = None) -> dict:
    """Pipeline completo para un piloto × tipo. Devuelve un dict serializable
    con el desglose entero (auditable)."""
    hoy = hoy or date.today()
    g = params["general"]
    pesos_tipo = pesos[m.tipo]
    subs = sub_scores(m, params, hoy)

    # Restricciones por evento ACTIVO (no depende del score)
    restricciones = sorted({e.tipo for e in m.eventos
                            if e.activo and params["eventos"].get(e.tipo, {}).get("activo_restringe")})

    n_min = _p(params, "general", "n_min_definitivo", tipo=m.tipo)
    n = m.n_aplicables
    confianza = clip(n / n_min, 0.0, 1.0) if n_min else 1.0

    # Sin ninguna variable de desempeño con dato (típicamente 0 servicios) no hay
    # evidencia sobre la que descontar antecedentes → sin score.
    sc, contrib = score_comportamental(subs, pesos_tipo, g.get("alpha_antecedentes", 1.0), g["score_max"])

    reg = aplicar_reglas(sc, m.reglas_activas, reglas.get("reglas", {}))
    estado = reg["estado"]
    if restricciones and estado != "BLOQUEADO":
        estado = "RESTRINGIDO"
    if sc is None:
        estado = "SIN_SCORE" if estado == "OK" else estado
        vigencia = "SIN_SCORE"
    else:
        vigencia = "DEFINITIVO" if n >= n_min else "PROVISIONAL"

    d = g["decimales"]
    red = lambda v: None if v is None else round(v + 1e-12, d)
    return {
        "piloto_id": m.piloto_id, "nombre": m.nombre, "tipo": m.tipo,
        "score_comportamental": red(sc),
        "score_final": red(reg["score_final"]),
        "banda": banda(reg["score_final"], params["bandas"]),
        "vigencia": vigencia, "confianza": round(confianza, 2),
        "n_aplicables": n, "n_min": n_min,
        "estado": estado, "restricciones_activas": restricciones,
        "tope_por_regla": reg["tope"], "alertas": reg["alertas"],
        "sub_scores": {k: ({**v, "score": None if v["score"] is None else round(v["score"], 3)}) for k, v in subs.items()},
        "contribuciones": {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                           for k, v in contrib.items()},
    }
