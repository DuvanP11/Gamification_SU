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
from datetime import date, datetime, timedelta

TIPOS = ("B2B", "RENT", "B2C")

EVENTOS = ("suspension_piloto", "suspension_pasajero", "invitacion_pibox",
           "invitacion_rent", "expulsion", "baneo_imei", "conducta_inapropiada")

# Bloques del modelo (v0.3, 2026-09-15):
#   POSITIVAS      → suman: la confianza que el piloto se GANA (experiencia, antigüedad,
#                    servicios sin novedad). Un piloto nuevo arranca en 0.
#   PENALIZACIONES → sólo descuentan: antecedentes + conductas operativas malas
#                    (cancelar, pagar tarde el recaudo, novedades en alto valor,
#                    no asistir a reservas, activación express). Portarse bien =
#                    descuento 0, nunca puntos.
POSITIVAS = ("finalizados", "antiguedad", "sin_novedades")
PENALIZACIONES = EVENTOS + ("activacion_express", "cancelacion_piloto", "recaudo_24h", "alto_valor", "cumplimiento_reservas")


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


def horas_habiles(inicio: datetime, fin: datetime) -> float:
    """Horas entre inicio y fin SIN contar sábados ni domingos (la "excepción
    de fin de semana" del recaudo). Un recaudo del viernes 18:00 tiene hasta el
    lunes 18:00. SQL: ver docs/METODOLOGIA.md §3.8."""
    if fin <= inicio:
        return 0.0
    total, t = 0.0, inicio
    while t < fin:
        siguiente_dia = (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        tramo_fin = min(fin, siguiente_dia)
        if t.weekday() < 5:            # 0..4 = lunes..viernes
            total += (tramo_fin - t).total_seconds() / 3600
        t = tramo_fin
    return total


# ────────────────────────────── entradas ──────────────────────────────
@dataclass
class Evento:
    tipo: str            # uno de EVENTOS
    fecha: date
    activo: bool = False # vigente hoy (restringe si el tipo lo indica)
    severidad: float | None = None  # override puntual; None = la del parámetro
    subtipo: str = ""    # p. ej. classification de conducta (ABUSIVE_LANGUAGE / PROSTITUTION_FRAUD)


@dataclass
class Recaudo:
    """Un recaudo contra entrega que el piloto debía abonar a Picap."""
    fecha_recaudo: datetime
    fecha_abono: datetime | None = None   # None = sigue sin pagar


@dataclass
class Documentos:
    """Habilitación documental (RUNT / Policía / SOAT / tecno). None = sin dato."""
    licencia_estado: str = ""            # p. ej. "ACTIVA"
    licencia_vence: date | None = None
    licencia_categorias: str = ""
    runt_driver_state: int | None = None # 1 = RUNT lo reconoce como conductor
    runt_mssg: str = ""
    runt_consultado: date | None = None
    policia_pendientes: int | None = None
    policia_consultado: date | None = None
    policia_recheck_nuevo: int | None = None
    policia_recheck_fecha: date | None = None
    soat_vence: date | None = None
    tecno_vence: date | None = None


@dataclass
class Metricas:
    """Agregados del piloto para UN tipo de servicio en la ventana de tasas.
    None = dato no disponible (≠ 0). Los conteos de reservas / alto valor /
    novedades sólo tienen sentido en los tipos donde aplican."""
    piloto_id: str
    tipo: str
    nombre: str = ""
    caso: str = ""                # sólo datos de prueba: qué escenario representa
    # Contexto (no puntúa, se muestra junto al score)
    driver_id: str = ""
    passenger_id: str = ""
    activado_piloto: date | None = None
    activado_pasajero: date | None = None
    calif_gamification: float | None = None   # gamification (vw_atr_driver_scoring_with_frauds: new_final_score_pibox/rent)
    gamif_puntos: float | None = None         # gamification: total_score_points
    gamif_final: float | None = None          # gamification: final_score
    calif_app: float | None = None            # calificación en la app (passengers.rating_as_driver__fl)
    activacion_express: int | None = None     # 1 = activado por la vía express (menos validación)
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
    recaudos: list[Recaudo] = field(default_factory=list)   # B2B: recaudos con no pago
    documentos: Documentos | None = None
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


def _c(cfg: dict, clave: str, tipo: str):
    """Valor de un parámetro de tasa: escalar o {tipo: valor}."""
    v = cfg[clave]
    return v[tipo] if isinstance(v, dict) else v


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
            sev = e.severidad
            if sev is None:
                sev = (cfg.get("severidad_por_subtipo") or {}).get(e.subtipo, cfg["severidad"])
            edades.append(edad)
            carga += sev * decaimiento(edad, cfg["semivida_dias"])
        s = sub_score_evento(carga, cfg["tope"], smax)
        out[var] = {"score": s, "detalle": {"n_eventos": len(evs), "en_ventana": len(edades),
                                            "carga": round(carga, 3), "tope": cfg["tope"],
                                            "edades_dias": edades}}

    # 1b) Antigüedad como piloto (positiva, saturante): un piloto recién activado
    #     vale 0 acá y va subiendo hasta dias_ref. Es la "desconfianza inicial".
    var = "antiguedad"
    dias_p = (hoy - m.activado_piloto).days if m.activado_piloto else m.dias_antiguedad
    if m.tipo not in aplica.get(var, []):
        no(var, "no_aplica")
    elif dias_p is None:
        no(var, "sin_dato")
    else:
        dias_p = max(0, dias_p)
        ref = _p(params, "volumen", "antiguedad", "dias_ref", tipo=m.tipo)
        out[var] = {"score": smax * clip(dias_p / ref, 0.0, 1.0),
                    "detalle": {"dias": dias_p, "dias_ref": ref,
                                "desde": (m.activado_piloto.isoformat() if m.activado_piloto else "registro")}}

    # 1c) Activación express (penalización): entró con menos validación. Descuenta
    #     completo el día de la activación y se apaga con semivida (ya demostró).
    var = "activacion_express"
    if m.tipo not in aplica.get(var, []):
        no(var, "no_aplica")
    elif m.activacion_express is None:
        no(var, "sin_dato")
    elif not m.activacion_express:
        out[var] = {"score": smax, "detalle": {"express": 0}}
    else:
        cfg = params["eventos"][var]
        edad = max(0, dias_p or 0)
        carga = decaimiento(edad, cfg["semivida_dias"])
        out[var] = {"score": sub_score_evento(carga, cfg["tope"], smax),
                    "detalle": {"express": 1, "dias_desde_activacion": edad, "carga": round(carga, 3), "tope": cfg["tope"]}}

    # 2) Cancelación propia (tasa, menos es mejor)
    var = "cancelacion_piloto"
    if m.tipo not in aplica[var]:
        no(var, "no_aplica")
    elif m.n_aplicables == 0:
        no(var, "sin_dato")
    else:
        c = params["tasas"][var]
        cruda = m.n_cancel_piloto / m.n_aplicables
        adj = tasa_ajustada(m.n_cancel_piloto, m.n_aplicables, _c(c, "p0", m.tipo), _c(c, "m", m.tipo))
        out[var] = {"score": rampa(adj, _c(c, "x_score0", m.tipo), _c(c, "x_score5", m.tipo), smax),
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
        adj = tasa_ajustada(x, n, _c(c, "p0", m.tipo), _c(c, "m", m.tipo))
        out[var] = {"score": rampa(adj, _c(c, "x_score0", m.tipo), _c(c, "x_score5", m.tipo), smax),
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
        expo = math.sqrt(clip(n_av / _c(c, "n_ref", m.tipo), 0, 1) * clip(prop / _c(c, "prop_ref", m.tipo), 0, 1))
        adj = tasa_ajustada(ok, n_av, _c(c, "p0", m.tipo), _c(c, "m", m.tipo))
        # Penalización pura: sin novedades en alto valor = 5 (descuento 0); con
        # novedades baja en proporción a la exposición (pocos servicios caros ≈ nada).
        s_neutro = smax
        s_desemp = rampa(adj, _c(c, "x_score0", m.tipo), _c(c, "x_score5", m.tipo), smax)
        s = s_neutro + expo * (s_desemp - s_neutro)
        out[var] = {"score": s, "detalle": {"n_alto_valor": n_av, "ok": ok, "proporcion": round(prop, 4),
                                            "exposicion": round(expo, 4), "cumplimiento_ajustado": round(adj, 4),
                                            "score_neutro": round(s_neutro, 3), "score_desempeno": round(s_desemp, 3)}}

    # 6) Recaudo pagado en ≤ 24 h hábiles (B2B). Cada recaudo que el piloto no
    #    abonó en el momento es un "episodio"; se mide qué fracción de esos
    #    episodios cerró dentro del límite (sin contar fin de semana).
    var = "recaudo_24h"
    if m.tipo not in aplica[var]:
        no(var, "no_aplica")
    elif not m.recaudos:
        no(var, "sin_dato")
    else:
        c = params["tasas"][var]
        lim = float(_c(c, "limite_horas", m.tipo)); fds = bool(c.get("excluir_fin_de_semana", True))
        ahora = datetime(hoy.year, hoy.month, hoy.day, 23, 59, 59)
        a_tiempo = tarde = pendientes = vencidos = 0
        horas_list = []
        for rc in m.recaudos:
            fin = rc.fecha_abono or ahora
            h = horas_habiles(rc.fecha_recaudo, fin) if fds else max(0.0, (fin - rc.fecha_recaudo).total_seconds() / 3600)
            if rc.fecha_abono is None:
                pendientes += 1
                if h > lim: vencidos += 1
                horas_list.append(None)
            else:
                horas_list.append(round(h, 1))
                if h <= lim: a_tiempo += 1
                else: tarde += 1
        # Un pendiente que aún está dentro del plazo no cuenta (todavía puede pagar).
        n = a_tiempo + tarde + vencidos
        if n == 0:
            no(var, "sin_dato")
        else:
            adj = tasa_ajustada(a_tiempo, n, _c(c, "p0", m.tipo), _c(c, "m", m.tipo))
            out[var] = {"score": rampa(adj, _c(c, "x_score0", m.tipo), _c(c, "x_score5", m.tipo), smax),
                        "detalle": {"episodios": len(m.recaudos), "a_tiempo": a_tiempo, "tarde": tarde,
                                    "vencidos_sin_pagar": vencidos, "pendientes_en_plazo": pendientes - vencidos,
                                    "n": n, "limite_horas": lim, "tasa_cruda": round(a_tiempo / n, 4),
                                    "tasa_ajustada": round(adj, 4), "horas_por_episodio": horas_list}}

    # 7) Cumplimiento de reservas (B2B)
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
            adj = tasa_ajustada(cum, n, _c(c, "p0", m.tipo), _c(c, "m", m.tipo))
            out[var] = {"score": rampa(adj, _c(c, "x_score0", m.tipo), _c(c, "x_score5", m.tipo), smax),
                        "detalle": {"cumplidas": cum, "incumplidas_atrib": inc, "n": n,
                                    "no_atribuibles_excluidas": m.n_res_no_atrib or 0,
                                    "tasa_cruda": round(cum / n, 4), "tasa_ajustada": round(adj, 4)}}
    return out


# ────────────────────────────── agregación ──────────────────────────────
def validar_pesos(pesos_tipo: dict[str, float], max_participacion) -> list[str]:
    """max_participacion: escalar o {positivas: x, penalizaciones: y}. Se valida
    dentro de cada bloque, que es donde la proporción manda."""
    avisos = []
    if not isinstance(max_participacion, dict):
        max_participacion = {"positivas": max_participacion, "penalizaciones": max_participacion}
    for nombre, vars_ in (("positivas", POSITIVAS), ("penalizaciones", PENALIZACIONES)):
        tot = sum((pesos_tipo.get(v) or 0) for v in vars_)
        if tot <= 0:
            avisos.append(f"la suma de pesos de {nombre} es 0"); continue
        lim = max_participacion.get(nombre, 1.0)
        for v in vars_:
            w = pesos_tipo.get(v) or 0
            if w < 0:
                avisos.append(f"peso negativo en {v}")
            elif w / tot > lim + 1e-9:
                avisos.append(f"{v} concentra {w/tot:.0%} de {nombre} > {lim:.0%} permitido")
    for k in pesos_tipo:
        if k not in POSITIVAS and k not in PENALIZACIONES:
            avisos.append(f"peso desconocido: {k}")
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
      D = Σ w·s / Σ w   sobre las variables POSITIVAS con dato (confianza ganada).
      P = Σ w_v·(1 − s_v/5) / Σ w_v   sobre las PENALIZACIONES aplicables (0 = nada que descontar).
      SCORE = D · (1 − α·P)
    Portarse bien en una penalización vale descuento 0, nunca suma puntos; cada
    penalización descuenta como máximo α·(w_v/Σw) → ninguna domina sola.
    Sin ninguna positiva con dato → None (sin evidencia)."""
    D, den_d = _promedio_ponderado(subs, pesos_tipo, POSITIVAS)
    if D is None:
        return None, {}
    contrib = {}
    for var in POSITIVAS:
        r = subs.get(var); w = pesos_tipo.get(var, 0) or 0
        if r and r.get("score") is not None and w > 0:
            contrib[var] = {"bloque": "positiva", "peso_efectivo": w / den_d, "aporte": w / den_d * r["score"]}
    num_p = den_p = 0.0
    for var in PENALIZACIONES:
        r = subs.get(var); w = pesos_tipo.get(var, 0) or 0
        if not r or r.get("score") is None or w <= 0:
            continue
        num_p += w * (1.0 - r["score"] / score_max); den_p += w
    P = (num_p / den_p) if den_p else 0.0
    for var in PENALIZACIONES:
        r = subs.get(var); w = pesos_tipo.get(var, 0) or 0
        if r and r.get("score") is not None and w > 0:
            contrib[var] = {"bloque": "penalizacion", "peso_efectivo": w / den_p,
                            "descuento": alpha * w / den_p * (1.0 - r["score"] / score_max)}
    contrib["_bloques"] = {"D_base": D, "P_penal": P, "factor": 1.0 - alpha * P, "alpha": alpha}
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


def observaciones(m: Metricas, subs: dict, vigencia: str, n_min: int, restricciones: list[str],
                  alertas: list[str], params: dict) -> list[str]:
    """Frases cortas, en lenguaje de Operaciones, con lo que más explica el
    score de este piloto. Se derivan de los sub-scores, no se escriben a mano."""
    obs = []
    # (singular, plural)
    NOMBRE_EV = {"suspension_piloto": ("Suspensión como piloto", "suspensiones como piloto"),
                 "suspension_pasajero": ("Suspensión como pasajero", "suspensiones como pasajero"),
                 "invitacion_pibox": ("Invitación Pibox", "invitaciones Pibox"),
                 "invitacion_rent": ("Invitación Rent", "invitaciones Rent"),
                 "expulsion": ("Expulsión", "expulsiones"), "baneo_imei": ("Baneo de IMEI", "baneos de IMEI"),
                 "conducta_inapropiada": ("Conducta inapropiada confirmada", "casos de conducta inapropiada confirmados")}
    dias_p = ((subs.get("antiguedad") or {}).get("detalle") or {}).get("dias")
    if dias_p is not None and dias_p < int(params["general"].get("dias_nuevo", 30)):
        obs.append(f"Piloto NUEVO: activado hace {dias_p} días — arranca en 0.0 y sube con lo que haga")
    if ((subs.get("activacion_express") or {}).get("detalle") or {}).get("express"):
        obs.append("Activado por la vía EXPRESS (menos validación al entrar)")
    if vigencia == "PROVISIONAL":
        obs.append(f"Piloto con pocos servicios en la ventana: {m.n_aplicables} de {n_min} necesarios (score provisional)")
    for r in restricciones:
        obs.append(f"{NOMBRE_EV[r][0]} VIGENTE")
    for var in EVENTOS:
        d = (subs.get(var) or {}).get("detalle")
        if not d or not d["en_ventana"]:
            continue
        ult = min(d["edades_dias"]); n = d["en_ventana"]
        obs.append(f"{n} {NOMBRE_EV[var][1]} (última hace {ult} días)" if n > 1 else f"{NOMBRE_EV[var][0]} hace {ult} días")
    d = (subs.get("cancelacion_piloto") or {}).get("detalle")
    if d and subs["cancelacion_piloto"]["score"] < 3:
        obs.append(f"Cancelación propia alta: {d['x']} de {d['n']} ({d['tasa_cruda']:.0%})")
    d = (subs.get("sin_novedades") or {}).get("detalle")
    if d and subs["sin_novedades"]["score"] < 3:
        obs.append(f"Novedades frecuentes: sólo {d['x']} de {d['n']} sin novedad y a tiempo ({d['tasa_cruda']:.0%})")
    d = (subs.get("alto_valor") or {}).get("detalle")
    if d and subs["alto_valor"]["score"] < d["score_neutro"] - 0.5:
        obs.append(f"Novedades en servicios de alto valor: {d['ok']} de {d['n_alto_valor']} bien")
    d = (subs.get("cumplimiento_reservas") or {}).get("detalle")
    if d and subs["cumplimiento_reservas"]["score"] < 3:
        obs.append(f"Incumple reservas: {d['incumplidas_atrib']} de {d['n']}")
    d = (subs.get("recaudo_24h") or {}).get("detalle")
    if d:
        if d["vencidos_sin_pagar"]:
            obs.append(f"Recaudo vencido sin pagar ({d['vencidos_sin_pagar']})")
        if d["tarde"]:
            obs.append(f"Recaudos pagados después de {int(d['limite_horas'])} h: {d['tarde']} de {d['n']}")
    for a in alertas:
        if a.startswith("doc: "):
            obs.append(a[5:])
        elif not a.startswith("recaudo_pendiente"):
            obs.append(f"Regla activa: {a}")
    return obs


def evaluar_documentos(d: Documentos | None, params: dict, hoy: date) -> dict:
    """Capa de habilitación: devuelve condiciones que restringen, alertan y
    avisos de vencimiento próximo. Nunca puntos."""
    out = {"restringe": [], "alertas": [], "por_vencer": [], "detalle": {}}
    if d is None:
        return out
    cfg = params.get("documentos") or {}
    pv = int(cfg.get("por_vencer_dias", 30))

    def cond(nombre, txt):
        efecto = cfg.get(nombre, "alerta")
        if efecto == "restringe": out["restringe"].append(txt)
        elif efecto == "alerta": out["alertas"].append(txt)

    def vence(nombre_cond, fecha, rotulo):
        if fecha is None:
            return
        dias = (fecha - hoy).days
        if dias < 0:
            cond(nombre_cond, f"{rotulo} vencido/a el {fecha.isoformat()} ({-dias} días)")
        elif dias <= pv:
            out["por_vencer"].append(f"{rotulo} vence el {fecha.isoformat()} (en {dias} días)")

    est = (d.licencia_estado or "").upper()
    if d.runt_mssg and "no se encontr" in d.runt_mssg.lower():
        cond("licencia_no_encontrada", "RUNT: no se encontró información de licencia")
    elif est and est != "ACTIVA":
        cond("licencia_no_activa", f"Licencia en estado {est} según RUNT")
    vence("licencia_vencida", d.licencia_vence, "Licencia de conducción")
    if d.runt_driver_state == 0:
        cond("runt_no_conductor", "RUNT no lo reconoce como conductor (driver_state = false)")
    if d.policia_pendientes == 1:
        cond("policia_pendientes", "Policía: TIENE asuntos pendientes con las autoridades")
    if d.policia_recheck_nuevo == 1:
        cond("policia_recheck_nuevo", "Recheck de Policía encontró antecedentes nuevos"
             + (f" ({d.policia_recheck_fecha.isoformat()})" if d.policia_recheck_fecha else ""))
    vence("soat_vencido", d.soat_vence, "SOAT")
    vence("tecno_vencida", d.tecno_vence, "Tecnomecánica")
    out["detalle"] = {
        "licencia": (est or "sin dato") + (f" · {d.licencia_categorias}" if d.licencia_categorias else "")
                    + (f" · vence {d.licencia_vence.isoformat()}" if d.licencia_vence else ""),
        "runt_consultado": d.runt_consultado.isoformat() if d.runt_consultado else None,
        "policia": {1: "con asuntos pendientes", 0: "sin asuntos pendientes"}.get(d.policia_pendientes, "sin dato")
                   + (f" · consultado {d.policia_consultado.isoformat()}" if d.policia_consultado else ""),
        "soat_vence": d.soat_vence.isoformat() if d.soat_vence else None,
        "tecno_vence": d.tecno_vence.isoformat() if d.tecno_vence else None,
    }
    return out


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

    # Piloto NUEVO (activado hace < dias_nuevo) sin servicios: arranca en 0.0 y sube
    # con lo que haga. Veterano sin servicios en la ventana: inactivo → sin score.
    dias_p = (hoy - m.activado_piloto).days if m.activado_piloto else m.dias_antiguedad
    es_nuevo = dias_p is not None and dias_p < int(g.get("dias_nuevo", 30))
    if n == 0 and not es_nuevo:
        sc, contrib = None, {}
    else:
        sc, contrib = score_comportamental(subs, pesos_tipo, g.get("alpha_antecedentes", 1.0), g["score_max"])
        if n == 0 and sc is not None:
            sc = 0.0; contrib["_bloques"] = {**contrib.get("_bloques", {}), "D_base": 0.0, "nota": "nuevo sin servicios"}

    reg = aplicar_reglas(sc, m.reglas_activas, reglas.get("reglas", {}))
    docs = evaluar_documentos(m.documentos, params, hoy) if m.tipo in (params.get("documentos") or {}).get("aplica_a", TIPOS) else evaluar_documentos(None, params, hoy)
    reg["alertas"].extend("doc: " + a for a in docs["alertas"])
    rc = subs.get("recaudo_24h", {}).get("detalle") or {}
    if rc.get("vencidos_sin_pagar") and params["tasas"]["recaudo_24h"].get("pendiente_alerta", True):
        reg["alertas"].append(f"recaudo_pendiente ({rc['vencidos_sin_pagar']} vencido/s sin pagar)")
    estado = reg["estado"]
    if (restricciones or docs["restringe"]) and estado != "BLOQUEADO":
        estado = "RESTRINGIDO"
    if sc is None:
        estado = "SIN_SCORE" if estado == "OK" else estado
        vigencia = "SIN_SCORE"
    else:
        vigencia = "DEFINITIVO" if n >= n_min else "PROVISIONAL"

    obs = observaciones(m, subs, vigencia, n_min, restricciones, reg["alertas"], params)
    obs = docs["restringe"] + obs + docs["por_vencer"]
    d = g["decimales"]
    red = lambda v: None if v is None else round(v + 1e-12, d)
    return {
        "piloto_id": m.piloto_id, "nombre": m.nombre, "tipo": m.tipo,
        "driver_id": m.driver_id, "passenger_id": m.passenger_id,
        "activado_piloto": m.activado_piloto.isoformat() if m.activado_piloto else None,
        "activado_pasajero": m.activado_pasajero.isoformat() if m.activado_pasajero else None,
        "calif_gamification": m.calif_gamification, "gamif_puntos": m.gamif_puntos, "gamif_final": m.gamif_final,
        "calif_app": m.calif_app,
        "caso": m.caso, "observaciones": obs,
        "score_comportamental": red(sc),
        "score_final": red(reg["score_final"]),
        "banda": banda(reg["score_final"], params["bandas"]),
        "vigencia": vigencia, "confianza": round(confianza, 2),
        "n_aplicables": n, "n_min": n_min,
        "estado": estado, "restricciones_activas": restricciones,
        "documentos": docs,
        "tope_por_regla": reg["tope"], "alertas": reg["alertas"],
        "sub_scores": {k: ({**v, "score": None if v["score"] is None else round(v["score"], 3)}) for k, v in subs.items()},
        "contribuciones": {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                           for k, v in contrib.items()},
    }
