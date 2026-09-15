# score/io.py — carga de configuración y datos (CSV) → Metricas.
from __future__ import annotations
import csv
from datetime import date, datetime
from pathlib import Path
import yaml
from .engine import Metricas, Evento, Recaudo, EVENTOS

RAIZ = Path(__file__).resolve().parent.parent


def cargar_yaml(nombre: str, raiz: Path = RAIZ) -> dict:
    with open(raiz / "config" / nombre, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_config(raiz: Path = RAIZ) -> tuple[dict, dict, dict]:
    return cargar_yaml("parametros.yaml", raiz), cargar_yaml("pesos.yaml", raiz), cargar_yaml("reglas.yaml", raiz)


def _int(v) -> int | None:
    v = (v or "").strip()
    return None if v == "" else int(float(v))


def _fecha(v) -> date:
    return datetime.strptime(v.strip()[:10], "%Y-%m-%d").date()


def _fecha_opc(v) -> date | None:
    v = (v or "").strip()
    return _fecha(v) if v else None


def _dt(v) -> datetime | None:
    v = (v or "").strip()
    if not v:
        return None
    return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S") if len(v) > 10 else datetime.strptime(v, "%Y-%m-%d")


def _float(v) -> float | None:
    v = (v or "").strip()
    return None if v == "" else float(v)


CAMPOS_INT = ["dias_antiguedad", "n_finalizados", "n_cancel_piloto", "n_cancel_pasajero",
              "n_cancel_plataforma", "n_otros_atribuibles", "n_sin_novedad_a_tiempo",
              "n_alto_valor", "n_alto_valor_ok", "n_res_cumplidas", "n_res_incumplidas_atrib",
              "n_res_cancel_atrib", "n_res_no_atrib"]
CAMPOS_CERO_POR_DEFECTO = {"n_finalizados", "n_cancel_piloto", "n_cancel_pasajero",
                           "n_cancel_plataforma", "n_otros_atribuibles"}


def cargar_datos(dir_datos: Path) -> list[Metricas]:
    """pilotos.csv (una fila por piloto×tipo) + eventos.csv + reglas_activas.csv."""
    eventos: dict[str, list[Evento]] = {}
    p_ev = dir_datos / "eventos.csv"
    if p_ev.exists():
        with open(p_ev, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["tipo_evento"] not in EVENTOS:
                    raise ValueError(f"tipo_evento desconocido: {r['tipo_evento']}")
                sev = r.get("severidad", "").strip()
                eventos.setdefault(r["piloto_id"], []).append(Evento(
                    tipo=r["tipo_evento"], fecha=_fecha(r["fecha"]),
                    activo=(r.get("activo", "0").strip() in ("1", "true", "True")),
                    severidad=float(sev) if sev else None))
    recaudos: dict[str, list[Recaudo]] = {}
    p_rc = dir_datos / "recaudos.csv"
    if p_rc.exists():
        with open(p_rc, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                recaudos.setdefault(r["piloto_id"], []).append(
                    Recaudo(fecha_recaudo=_dt(r["fecha_recaudo"]), fecha_abono=_dt(r.get("fecha_abono"))))
    reglas: dict[str, list[str]] = {}
    p_rg = dir_datos / "reglas_activas.csv"
    if p_rg.exists():
        with open(p_rg, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                reglas.setdefault(r["piloto_id"], []).append(r["regla"].strip())
    out = []
    with open(dir_datos / "pilotos.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            kw = {"piloto_id": r["piloto_id"], "tipo": r["tipo"].strip().upper(), "nombre": r.get("nombre", ""),
                  "caso": (r.get("caso") or "").strip(),
                  "driver_id": (r.get("driver_id") or "").strip(), "passenger_id": (r.get("passenger_id") or "").strip(),
                  "activado_piloto": _fecha_opc(r.get("activado_piloto")),
                  "activado_pasajero": _fecha_opc(r.get("activado_pasajero")),
                  "calif_gamification": _float(r.get("calif_gamification")), "calif_app": _float(r.get("calif_app"))}
            for c in CAMPOS_INT:
                v = _int(r.get(c))
                if v is None and c in CAMPOS_CERO_POR_DEFECTO:
                    v = 0
                kw[c] = v
            kw["eventos"] = eventos.get(r["piloto_id"], [])
            kw["recaudos"] = recaudos.get(r["piloto_id"], [])
            kw["reglas_activas"] = reglas.get(r["piloto_id"], [])
            out.append(Metricas(**kw))
    return out
