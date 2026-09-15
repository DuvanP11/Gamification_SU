# score/io.py — carga de configuración y datos (CSV) → Metricas.
from __future__ import annotations
import csv
from datetime import date, datetime
from pathlib import Path
import yaml
from .engine import Metricas, Evento, Recaudo, Documentos, EVENTOS

RAIZ = Path(__file__).resolve().parent.parent


def cargar_yaml(nombre: str, raiz: Path = RAIZ) -> dict:
    with open(raiz / "config" / nombre, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_config(raiz: Path = RAIZ) -> tuple[dict, dict, dict]:
    return cargar_yaml("parametros.yaml", raiz), cargar_yaml("pesos.yaml", raiz), cargar_yaml("reglas.yaml", raiz)


def _int(v) -> int | None:
    v = (v or "").strip()
    return None if v in ("", "\\N", "NULL", "null") else int(float(v))


def _fecha(v) -> date:
    return datetime.strptime(v.strip()[:10], "%Y-%m-%d").date()


def _fecha_opc(v) -> date | None:
    v = (v or "").strip()
    return _fecha(v) if v and v not in ("\\N", "NULL", "1970-01-01") else None


def _dt(v) -> datetime | None:
    v = (v or "").strip()
    if not v:
        return None
    return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S") if len(v) > 10 else datetime.strptime(v, "%Y-%m-%d")


def _float(v) -> float | None:
    v = (v or "").strip()
    if v in ("", "\\N", "NULL", "null", "nan"):
        return None
    return float(v)


CAMPOS_INT = ["dias_antiguedad", "n_finalizados", "n_cancel_piloto", "n_cancel_pasajero",
              "n_cancel_plataforma", "n_otros_atribuibles", "n_sin_novedad_a_tiempo",
              "n_alto_valor", "n_alto_valor_ok", "n_res_cumplidas", "n_res_incumplidas_atrib",
              "n_res_cancel_atrib", "n_res_no_atrib"]
CAMPOS_CERO_POR_DEFECTO = {"n_finalizados", "n_cancel_piloto", "n_cancel_pasajero",
                           "n_cancel_plataforma", "n_otros_atribuibles"}


def fuentes_de_datos(raiz: Path = RAIZ) -> list[str]:
    """Carpetas data*/ con un pilotos.csv (ficticios, reales, …)."""
    return sorted(d.name for d in raiz.glob("data*") if (d / "pilotos.csv").exists())


def cargar_datos(dir_datos: Path) -> list[Metricas]:
    """pilotos.csv (una fila por piloto×tipo) + eventos.csv + reglas_activas.csv."""
    # eventos*.csv: todos se suman. Si un piloto tiene eventos con `origen=historial`
    # de un tipo, se descartan los de `origen=flag` (estado sin fecha) del mismo tipo,
    # para no contar dos veces la misma suspensión vigente.
    eventos: dict[str, list[Evento]] = {}
    flags: dict[str, list[Evento]] = {}
    con_historial: set[tuple[str, str]] = set()
    for p_ev in sorted(dir_datos.glob("eventos*.csv")):
        with open(p_ev, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["tipo_evento"] not in EVENTOS:
                    raise ValueError(f"tipo_evento desconocido: {r['tipo_evento']}")
                sev = (r.get("severidad") or "").strip()
                ev = Evento(tipo=r["tipo_evento"], fecha=_fecha(r["fecha"]),
                            activo=((r.get("activo") or "0").strip() in ("1", "true", "True")),
                            severidad=float(sev) if sev else None,
                            subtipo=(r.get("subtipo") or "").strip())
                if (r.get("origen") or "").strip() == "flag":
                    flags.setdefault(r["piloto_id"], []).append(ev)
                else:
                    eventos.setdefault(r["piloto_id"], []).append(ev)
                    if (r.get("origen") or "").strip() == "historial":
                        con_historial.add((r["piloto_id"], r["tipo_evento"]))
    for pid, evs in flags.items():
        for ev in evs:
            if (pid, ev.tipo) not in con_historial:
                eventos.setdefault(pid, []).append(ev)
    recaudos: dict[str, list[Recaudo]] = {}
    for p_rc in sorted(dir_datos.glob("recaudos*.csv")):
        with open(p_rc, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                recaudos.setdefault(r["piloto_id"], []).append(
                    Recaudo(fecha_recaudo=_dt(r["fecha_recaudo"]), fecha_abono=_dt(r.get("fecha_abono"))))
    documentos: dict[str, Documentos] = {}
    p_dc = dir_datos / "documentos.csv"
    if p_dc.exists():
        with open(p_dc, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                documentos[r["piloto_id"]] = Documentos(
                    licencia_estado=(r.get("licencia_estado") or "").strip(),
                    licencia_vence=_fecha_opc(r.get("licencia_vence")),
                    licencia_categorias=(r.get("licencia_categorias") or "").strip(),
                    runt_driver_state=_int(r.get("runt_driver_state")),
                    runt_mssg=(r.get("runt_mssg") or "").strip(),
                    runt_consultado=_fecha_opc(r.get("runt_consultado")),
                    policia_pendientes=_int(r.get("policia_pendientes")),
                    policia_consultado=_fecha_opc(r.get("policia_consultado")),
                    policia_recheck_nuevo=_int(r.get("policia_recheck_nuevo")),
                    policia_recheck_fecha=_fecha_opc(r.get("policia_recheck_fecha")),
                    soat_vence=_fecha_opc(r.get("soat_vence")),
                    tecno_vence=_fecha_opc(r.get("tecno_vence")))
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
                  "calif_gamification": _float(r.get("calif_gamification")), "calif_app": _float(r.get("calif_app")),
                  "gamif_puntos": _float(r.get("gamif_puntos")), "gamif_final": _float(r.get("gamif_final")),
                  "activacion_express": _int(r.get("activacion_express"))}
            for c in CAMPOS_INT:
                v = _int(r.get(c))
                if v is None and c in CAMPOS_CERO_POR_DEFECTO:
                    v = 0
                kw[c] = v
            kw["eventos"] = eventos.get(r["piloto_id"], [])
            kw["recaudos"] = recaudos.get(r["piloto_id"], [])
            kw["documentos"] = documentos.get(r["piloto_id"])
            kw["reglas_activas"] = reglas.get(r["piloto_id"], [])
            out.append(Metricas(**kw))
    return out
