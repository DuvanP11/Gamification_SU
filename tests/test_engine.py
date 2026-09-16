# tests/test_engine.py — python3 -m unittest -v
import unittest
from datetime import date
from pathlib import Path
from datetime import datetime
from score.engine import (rampa, tasa_ajustada, decaimiento, sub_score_evento, sub_score_volumen, horas_habiles,
                          Metricas, Evento, Recaudo, evaluar, validar_pesos, TIPOS, EVENTOS)
from score.io import cargar_config, cargar_datos, RAIZ

HOY = date(2026, 9, 15)
PARAMS, PESOS, REGLAS = cargar_config()


def ev(m: Metricas):
    return evaluar(m, PARAMS, PESOS, REGLAS, HOY)


class Primitivas(unittest.TestCase):
    def test_rampa_ambas_direcciones(self):
        self.assertEqual(rampa(0.03, 0.30, 0.03), 5.0)      # menos es mejor
        self.assertEqual(rampa(0.30, 0.30, 0.03), 0.0)
        self.assertEqual(rampa(0.50, 0.30, 0.03), 0.0)      # recorte
        self.assertAlmostEqual(rampa(0.165, 0.30, 0.03), 2.5)
        self.assertEqual(rampa(0.97, 0.60, 0.97), 5.0)      # más es mejor
        self.assertEqual(rampa(0.0, 0.60, 0.97), 0.0)

    def test_tasa_ajustada(self):
        self.assertEqual(tasa_ajustada(0, 0, 0.08, 10), 0.08)          # sin datos → prior
        self.assertAlmostEqual(tasa_ajustada(1, 3, 0.08, 10), 1.8 / 13)  # 1 de 3 no es 33 %
        self.assertAlmostEqual(tasa_ajustada(100, 1000, 0.08, 10), 100.8 / 1010, places=6)

    def test_decaimiento(self):
        self.assertEqual(decaimiento(0, 180), 1.0)
        self.assertAlmostEqual(decaimiento(180, 180), 0.5)
        self.assertAlmostEqual(decaimiento(360, 180), 0.25)

    def test_sub_score_evento_acotado(self):
        self.assertEqual(sub_score_evento(0, 2), 5.0)
        self.assertEqual(sub_score_evento(1, 2), 2.5)
        self.assertEqual(sub_score_evento(9, 2), 0.0)

    def test_volumen_saturante(self):
        self.assertEqual(sub_score_volumen(0, 150), 0.0)
        self.assertEqual(sub_score_volumen(150, 150), 5.0)
        self.assertEqual(sub_score_volumen(10_000, 150), 5.0)
        self.assertLess(sub_score_volumen(10, 150), sub_score_volumen(50, 150))


class Casos(unittest.TestCase):
    def test_pesos_validos(self):
        for t in TIPOS:
            self.assertEqual(validar_pesos(PESOS[t], PARAMS["general"]["max_participacion_peso"]), [], t)

    def test_rango_0_5_extremos(self):
        # Todo al peor: muchas cancelaciones, sin novedades 0, todos los eventos hoy
        m = Metricas("X", "B2B", n_finalizados=1, n_cancel_piloto=99, n_sin_novedad_a_tiempo=0,
                     n_alto_valor=50, n_alto_valor_ok=0, n_res_cumplidas=0, n_res_incumplidas_atrib=20,
                     recaudos=[Recaudo(datetime(2026, 8, 3, 9)) for _ in range(10)],
                     eventos=[Evento(e, HOY) for e in EVENTOS for _ in range(5)])
        r = ev(m); self.assertEqual(r["score_final"], 0.0)
        # Todo al mejor
        m = Metricas("Y", "B2B", n_finalizados=500, n_cancel_piloto=0, n_sin_novedad_a_tiempo=500,
                     n_alto_valor=100, n_alto_valor_ok=100, n_res_cumplidas=50, n_res_incumplidas_atrib=0,
                     recaudos=[Recaudo(datetime(2026, 8, 3, 9), datetime(2026, 8, 3, 12)) for _ in range(10)])
        r = ev(m); self.assertEqual(r["score_final"], 5.0)

    def test_cero_servicios_sin_score(self):
        r = ev(Metricas("Z", "B2C"))
        self.assertIsNone(r["score_final"]); self.assertEqual(r["estado"], "SIN_SCORE")
        # ni siquiera con antecedentes: no hay evidencia de desempeño sobre la que descontar
        r = ev(Metricas("Z", "B2C", eventos=[Evento("suspension_piloto", HOY)]))
        self.assertIsNone(r["score_final"])

    def test_pocos_servicios_provisional(self):
        r = ev(Metricas("N", "RENT", n_finalizados=3, n_cancel_piloto=1))
        self.assertEqual(r["vigencia"], "PROVISIONAL"); self.assertLess(r["confianza"], 1)
        # 1 de 4 (25 % crudo) NO se lee como 25 %: el prior lo lleva hacia la referencia p0
        d = r["sub_scores"]["cancelacion_piloto"]["detalle"]
        p0 = PARAMS["tasas"]["cancelacion_piloto"]["p0"]; p0 = p0["RENT"] if isinstance(p0, dict) else p0
        lo, hi = sorted([d["tasa_cruda"], p0])
        self.assertGreater(d["tasa_ajustada"], lo); self.assertLess(d["tasa_ajustada"], hi)

    def test_no_aplica_sale_del_calculo(self):
        r = ev(Metricas("R", "RENT", n_finalizados=50))
        for v in ("alto_valor", "sin_novedades", "cumplimiento_reservas", "recaudo_24h"):
            self.assertEqual(r["sub_scores"][v]["motivo"], "no_aplica")
            self.assertNotIn(v, r["contribuciones"])
        r = ev(Metricas("B", "B2B", n_finalizados=50))
        self.assertEqual(r["sub_scores"]["baneo_imei"]["motivo"], "no_aplica")

    def test_historial_limpio_no_suma(self):
        base = dict(n_finalizados=50, n_cancel_piloto=5, n_cancel_pasajero=30)
        limpio = ev(Metricas("A", "RENT", **base))
        b = limpio["contribuciones"]["_bloques"]
        self.assertEqual(b["B_menos"], 0.0)
        self.assertAlmostEqual(limpio["score_final"], round(min(5.0, b["A_base"] + b["ganancia"]), 1))

    def test_suspension_vieja_vs_reciente(self):
        base = dict(n_finalizados=200, n_cancel_piloto=4)
        vieja = ev(Metricas("V", "RENT", eventos=[Evento("suspension_piloto", date(2024, 9, 15))], **base))
        recien = ev(Metricas("R", "RENT", eventos=[Evento("suspension_piloto", date(2026, 9, 10))], **base))
        limpio = ev(Metricas("L", "RENT", **base))
        self.assertLess(recien["score_final"], vieja["score_final"])
        self.assertLessEqual(vieja["score_final"], limpio["score_final"])
        self.assertGreaterEqual(vieja["score_final"], limpio["score_final"] - 0.2)  # 2 años: casi nada

    def test_multiples_suspensiones_acumulan_pero_saturan(self):
        base = dict(n_finalizados=200, n_cancel_piloto=4)
        una = ev(Metricas("1", "RENT", eventos=[Evento("suspension_piloto", HOY)], **base))
        tres = ev(Metricas("3", "RENT", eventos=[Evento("suspension_piloto", HOY)] * 3, **base))
        diez = ev(Metricas("10", "RENT", eventos=[Evento("suspension_piloto", HOY)] * 10, **base))
        self.assertLess(tres["score_final"], una["score_final"])
        self.assertEqual(tres["sub_scores"]["suspension_piloto"]["score"], 0.0)
        self.assertEqual(diez["score_final"], tres["score_final"])    # tope: no sigue cayendo
        self.assertGreater(diez["score_final"], 0)                    # una sola variable no lo hunde

    def test_cancelacion_pasajero_no_castiga(self):
        a = ev(Metricas("A", "RENT", n_finalizados=50, n_cancel_piloto=2, n_cancel_pasajero=0))
        b = ev(Metricas("B", "RENT", n_finalizados=50, n_cancel_piloto=2, n_cancel_pasajero=40))
        self.assertEqual(a["sub_scores"]["cancelacion_piloto"]["score"], b["sub_scores"]["cancelacion_piloto"]["score"])

    def test_alto_valor_no_premia_por_caro(self):
        base = dict(n_finalizados=100, n_cancel_piloto=2, n_sin_novedad_a_tiempo=95)
        sin_av = ev(Metricas("0", "B2B", **base))
        caro_mal = ev(Metricas("M", "B2B", n_alto_valor=30, n_alto_valor_ok=18, **base))
        caro_bien = ev(Metricas("B", "B2B", n_alto_valor=30, n_alto_valor_ok=30, **base))
        pocos = ev(Metricas("P", "B2B", n_alto_valor=2, n_alto_valor_ok=2, **base))
        self.assertEqual(sin_av["sub_scores"]["alto_valor"]["motivo"], "sin_dato")
        self.assertLess(caro_mal["score_final"], sin_av["score_final"])
        self.assertGreater(caro_bien["score_final"], caro_mal["score_final"])
        neutro = pocos["sub_scores"]["alto_valor"]["detalle"]["score_neutro"]
        self.assertLess(abs(pocos["sub_scores"]["alto_valor"]["score"] - neutro), 0.5)  # poca exposición ≈ neutro

    def test_reservas_no_atribuibles_fuera(self):
        a = ev(Metricas("A", "B2B", n_finalizados=50, n_res_cumplidas=20, n_res_incumplidas_atrib=2, n_res_no_atrib=0))
        b = ev(Metricas("B", "B2B", n_finalizados=50, n_res_cumplidas=20, n_res_incumplidas_atrib=2, n_res_no_atrib=15))
        self.assertEqual(a["sub_scores"]["cumplimiento_reservas"]["score"], b["sub_scores"]["cumplimiento_reservas"]["score"])

    def test_reglas_gate(self):
        base = dict(n_finalizados=200, n_cancel_piloto=2)
        tope = ev(Metricas("T", "B2B", reglas_activas=["cuenta_nueva_retiro_alto"], **base))
        self.assertEqual(tope["score_final"], 2.5); self.assertGreater(tope["score_comportamental"], 2.5)
        blq = ev(Metricas("B", "B2B", reglas_activas=["imei_compartido"], **base))
        self.assertEqual(blq["estado"], "BLOQUEADO"); self.assertGreater(blq["score_final"], 4)
        al = ev(Metricas("A", "B2B", reglas_activas=["cancelaciones_en_racha"], **base))
        self.assertEqual(al["estado"], "OK"); self.assertEqual(al["score_final"], al["score_comportamental"])

    def test_evento_activo_restringe(self):
        r = ev(Metricas("I", "RENT", n_finalizados=100, eventos=[Evento("baneo_imei", HOY, activo=True)]))
        self.assertEqual(r["estado"], "RESTRINGIDO"); self.assertIn("baneo_imei", r["restricciones_activas"])

    def test_horas_habiles_salta_fin_de_semana(self):
        # viernes 2026-09-04 17:00 → lunes 2026-09-07 15:00: 7 h del viernes + 15 h del lunes = 22 h
        self.assertAlmostEqual(horas_habiles(datetime(2026, 9, 4, 17), datetime(2026, 9, 7, 15)), 22.0)
        # dentro de un mismo día hábil
        self.assertAlmostEqual(horas_habiles(datetime(2026, 9, 8, 9), datetime(2026, 9, 8, 18, 30)), 9.5)
        # sábado completo no cuenta
        self.assertAlmostEqual(horas_habiles(datetime(2026, 9, 5, 0), datetime(2026, 9, 6, 0)), 0.0)
        self.assertEqual(horas_habiles(datetime(2026, 9, 8, 9), datetime(2026, 9, 8, 8)), 0.0)

    def test_recaudo_24h(self):
        base = dict(n_finalizados=80, n_cancel_piloto=2)
        sin = ev(Metricas("0", "B2B", **base))
        self.assertEqual(sin["sub_scores"]["recaudo_24h"]["motivo"], "sin_dato")
        vie = datetime(2026, 9, 4, 17)
        ok = ev(Metricas("A", "B2B", recaudos=[Recaudo(vie, datetime(2026, 9, 7, 15))], **base))   # 22 h hábiles
        self.assertEqual(ok["sub_scores"]["recaudo_24h"]["detalle"]["a_tiempo"], 1)
        tarde = ev(Metricas("B", "B2B", recaudos=[Recaudo(vie, datetime(2026, 9, 8, 15))], **base))  # 46 h hábiles
        self.assertEqual(tarde["sub_scores"]["recaudo_24h"]["detalle"]["tarde"], 1)
        self.assertLess(tarde["score_final"], ok["score_final"])
        venc = ev(Metricas("C", "B2B", recaudos=[Recaudo(datetime(2026, 9, 8, 9))], **base))       # sin pagar, vencido
        self.assertEqual(venc["sub_scores"]["recaudo_24h"]["detalle"]["vencidos_sin_pagar"], 1)
        self.assertTrue(any(a.startswith("recaudo_pendiente") for a in venc["alertas"]))
        self.assertTrue(any("vencido" in o for o in venc["observaciones"]))
        plazo = ev(Metricas("D", "B2B", recaudos=[Recaudo(datetime(2026, 9, 15, 10))], **base))     # pendiente en plazo
        self.assertEqual(plazo["sub_scores"]["recaudo_24h"]["motivo"], "sin_dato")
        self.assertEqual(plazo["alertas"], [])
        self.assertEqual(ev(Metricas("R", "RENT", recaudos=[Recaudo(vie)], **base))["sub_scores"]["recaudo_24h"]["motivo"], "no_aplica")

    def test_recaudo_entregado(self):
        base = dict(dias_antiguedad=400, n_finalizados=80, n_cancel_piloto=2)
        d = lambda r: r["sub_scores"]["recaudo_entregado"]["detalle"]
        sin = ev(Metricas("0", "B2B", **base))
        self.assertEqual(sin["sub_scores"]["recaudo_entregado"]["motivo"], "sin_dato")
        lun = datetime(2026, 9, 7, 9)
        # Abonado en el momento: recaudo_24h NO lo ve (no es episodio), entregado SÍ y suma.
        al_toque = [Recaudo(lun, lun.replace(minute=0, second=20), monto=50000, fecha_saldado=lun) for _ in range(8)]
        ok = ev(Metricas("A", "B2B", recaudos=al_toque, **base))
        self.assertEqual(ok["sub_scores"]["recaudo_24h"]["motivo"], "sin_dato")
        self.assertEqual(d(ok)["bien"], 8); self.assertEqual(d(ok)["monto_total"], 400000)
        self.assertGreater(ok["contribuciones"]["recaudo_entregado"]["aporte"], 0)
        # Saldado tarde = novedad (resta); fecha_saldado manda sobre fecha_abono.
        tarde = ev(Metricas("B", "B2B", recaudos=[Recaudo(lun, lun, monto=50000, fecha_saldado=datetime(2026, 9, 9, 12))] * 8, **base))
        self.assertEqual(d(tarde)["novedad"], 8); self.assertLess(tarde["contribuciones"]["recaudo_entregado"]["aporte"], 0)
        # Sin saldar y vencido = no pago: pesa doble y deja observación con el monto.
        np_ = ev(Metricas("C", "B2B", recaudos=[Recaudo(lun, monto=120000)] * 2 + al_toque[:2], **base))
        self.assertEqual((d(np_)["no_pago"], d(np_)["bien"], d(np_)["n"]), (2, 2, 6.0))
        self.assertEqual(d(np_)["monto_no_pagado"], 240000)
        self.assertTrue(any(o.startswith("Recaudos sin entregar: 2") for o in np_["observaciones"]))
        # Mismo caso pero saldado tarde en vez de no pagar: la novedad castiga menos que el no pago.
        nov = ev(Metricas("C2", "B2B", recaudos=[Recaudo(lun, monto=120000, fecha_saldado=datetime(2026, 9, 10, 9))] * 2 + al_toque[:2], **base))
        self.assertLess(np_["sub_scores"]["recaudo_entregado"]["score"], nov["sub_scores"]["recaudo_entregado"]["score"])
        # Pendiente pero en plazo: no cuenta. CSV viejo (sin fecha_saldado): usa el abono.
        plazo = ev(Metricas("D", "B2B", recaudos=[Recaudo(datetime(2026, 9, 15, 10), monto=1)], **base))
        self.assertEqual(plazo["sub_scores"]["recaudo_entregado"]["motivo"], "sin_dato")
        viejo = ev(Metricas("E", "B2C", recaudos=[Recaudo(lun, datetime(2026, 9, 7, 15))], **base))
        self.assertEqual(d(viejo)["bien"], 1)
        self.assertEqual(ev(Metricas("R", "RENT", recaudos=al_toque, **base))["sub_scores"]["recaudo_entregado"]["motivo"], "no_aplica")

    def test_calificacion_pasajero(self):
        base = dict(dias_antiguedad=400, n_finalizados=100, n_cancel_piloto=5)
        sub = lambda r: r["sub_scores"]["calificacion_pasajero"]
        for t in ("RENT", "B2C"):
            self.assertEqual(sub(ev(Metricas("0", t, **base)))["motivo"], "sin_dato")
            self.assertEqual(sub(ev(Metricas("0", t, n_calificados=0, suma_calificaciones=0, **base)))["motivo"], "sin_dato")
        # B2B: la nota es ~siempre 5 en la población (calibración 2026-09-16) → no aplica
        self.assertEqual(sub(ev(Metricas("0", "B2B", n_calificados=100, suma_calificaciones=500, **base)))["motivo"], "no_aplica")
        p0 = PARAMS["tasas"]["calificacion_pasajero"]["p0"]["RENT"]
        ref = ev(Metricas("R", "RENT", n_calificados=100, suma_calificaciones=p0 * 100, **base))  # = referencia
        mejor = ev(Metricas("M", "RENT", n_calificados=100, suma_calificaciones=500, **base))  # todo cincos
        peor = ev(Metricas("P", "RENT", n_calificados=100, suma_calificaciones=380, **base))   # promedio 3.8
        self.assertAlmostEqual(ref["contribuciones"]["calificacion_pasajero"]["aporte"], 0, delta=0.05)
        self.assertGreater(mejor["contribuciones"]["calificacion_pasajero"]["aporte"], 0)
        self.assertLess(peor["contribuciones"]["calificacion_pasajero"]["aporte"], 0)
        self.assertGreater(mejor["score_final"], ref["score_final"]); self.assertLess(peor["score_final"], ref["score_final"])
        self.assertEqual(sub(peor)["detalle"]["promedio_crudo"], 3.8)
        self.assertTrue(any(o.startswith("Calificación baja") for o in peor["observaciones"]))
        # Pocas notas no dan el máximo: 3 cincos quedan cerca de la referencia (suavizado).
        pocas = ev(Metricas("Q", "RENT", n_calificados=3, suma_calificaciones=15, **base))
        self.assertLess(sub(pocas)["detalle"]["promedio_ajustado"], 4.9)
        self.assertLess(pocas["contribuciones"]["calificacion_pasajero"]["aporte"], mejor["contribuciones"]["calificacion_pasajero"]["aporte"])
        # Rent por fin tiene una mixta: la base ya no llega sola a 5.
        self.assertLess(ref["contribuciones"]["_bloques"]["base_max"], 5)

    def test_observaciones_automaticas(self):
        r = ev(Metricas("N", "RENT", n_finalizados=3, n_cancel_piloto=12, eventos=[Evento("suspension_piloto", date(2026, 9, 5))]))
        txt = " | ".join(r["observaciones"])
        self.assertIn("pocos servicios", txt); self.assertIn("Suspensión como piloto hace 10 días", txt); self.assertIn("Cancelación propia alta", txt)
        self.assertEqual(ev(Metricas("L", "RENT", n_finalizados=200, n_cancel_piloto=2))["observaciones"], [])

    def test_datos_ejemplo_cargan_y_estan_en_rango(self):
        for m in cargar_datos(RAIZ / "data"):
            r = ev(m)
            if r["score_final"] is not None:
                self.assertGreaterEqual(r["score_final"], 0.0); self.assertLessEqual(r["score_final"], 5.0)


if __name__ == "__main__":
    unittest.main()


class BloquesV04(unittest.TestCase):
    """v0.4: base (experiencia+antigüedad) + mixtas que suman o restan + negativas; el nuevo arranca en 0."""
    def test_cancelacion_solo_resta(self):
        base = dict(dias_antiguedad=400, n_finalizados=100)
        ref = ev(Metricas("R", "RENT", n_cancel_piloto=int(100 * 0.34 / 0.66), **base))   # ≈ mediana RENT (34 %)
        mejor = ev(Metricas("M", "RENT", n_cancel_piloto=0, **base))
        peor = ev(Metricas("P", "RENT", n_cancel_piloto=150, **base))
        self.assertEqual(mejor["contribuciones"]["cancelacion_piloto"]["aporte"], 0.0)        # cancelar menos NO suma
        self.assertAlmostEqual(ref["contribuciones"]["cancelacion_piloto"]["aporte"], 0, delta=0.05)
        self.assertLess(peor["contribuciones"]["cancelacion_piloto"]["aporte"], 0)             # cancelar más resta
        self.assertEqual(mejor["score_final"], ref["score_final"]); self.assertLess(peor["score_final"], ref["score_final"])
        # en Rent no hay mixtas: el score de un piloto sin problemas es su base ganada
        self.assertAlmostEqual(ref["score_final"], round(ref["contribuciones"]["_bloques"]["A_base"], 1), delta=0.1)

    def test_mixta_suma_o_resta_segun_la_referencia(self):
        base = dict(dias_antiguedad=400, n_finalizados=100, n_cancel_piloto=5)
        ref = ev(Metricas("R", "B2B", n_sin_novedad_a_tiempo=90, **base))     # = referencia 90 %
        mejor = ev(Metricas("M", "B2B", n_sin_novedad_a_tiempo=100, **base))
        peor = ev(Metricas("P", "B2B", n_sin_novedad_a_tiempo=60, **base))
        self.assertGreater(mejor["contribuciones"]["sin_novedades"]["aporte"], 0)
        self.assertLess(peor["contribuciones"]["sin_novedades"]["aporte"], 0)
        self.assertAlmostEqual(ref["contribuciones"]["sin_novedades"]["aporte"], 0, delta=0.05)
        self.assertGreater(mejor["score_final"], ref["score_final"]); self.assertLess(peor["score_final"], ref["score_final"])

    def test_las_demas_mixtas_tambien(self):
        from score.engine import Recaudo
        base = dict(dias_antiguedad=400, n_finalizados=100, n_cancel_piloto=5)
        ok = ev(Metricas("A", "B2B", n_sin_novedad_a_tiempo=100, n_res_cumplidas=30, n_res_incumplidas_atrib=0, n_alto_valor=30, n_alto_valor_ok=30,
                         recaudos=[Recaudo(datetime(2026, 9, 8, 9), datetime(2026, 9, 8, 12))] * 5, **base))
        mal = ev(Metricas("B", "B2B", n_sin_novedad_a_tiempo=60, n_res_cumplidas=5, n_res_incumplidas_atrib=10, n_alto_valor=30, n_alto_valor_ok=10,
                          recaudos=[Recaudo(datetime(2026, 9, 1, 9), datetime(2026, 9, 8, 9))] * 5, **base))
        for v in ("sin_novedades", "cumplimiento_reservas", "alto_valor", "recaudo_24h"):
            self.assertGreater(ok["contribuciones"][v]["aporte"], 0, v); self.assertLess(mal["contribuciones"][v]["aporte"], 0, v)
        self.assertGreater(ok["score_final"], mal["score_final"])

    def test_piloto_nuevo_arranca_en_cero_y_sube(self):
        nuevo0 = ev(Metricas("N0", "RENT", activado_piloto=date(2026, 9, 14)))
        self.assertEqual(nuevo0["score_final"], 0.0); self.assertEqual(nuevo0["vigencia"], "PROVISIONAL")
        self.assertTrue(any("NUEVO" in o for o in nuevo0["observaciones"]))
        n1 = ev(Metricas("N1", "RENT", activado_piloto=date(2026, 9, 5), n_finalizados=8, n_cancel_piloto=0))
        n2 = ev(Metricas("N2", "RENT", activado_piloto=date(2026, 8, 20), n_finalizados=40, n_cancel_piloto=0))
        vet = ev(Metricas("V", "RENT", activado_piloto=date(2024, 1, 1), n_finalizados=200, n_cancel_piloto=0))
        self.assertGreater(n1["score_final"], 0.0); self.assertGreater(n2["score_final"], n1["score_final"]); self.assertGreater(vet["score_final"], n2["score_final"])
        self.assertLessEqual(n1["score_final"], 5 - PARAMS["general"]["base_confianza_max"] + 0.5)   # sin base ganada no puede volar
        self.assertIsNone(ev(Metricas("I", "RENT", activado_piloto=date(2024, 1, 1)))["score_final"])   # veterano inactivo

    def test_activacion_express_penaliza_y_se_apaga(self):
        base = dict(n_finalizados=60, n_cancel_piloto=0)
        normal = ev(Metricas("A", "RENT", activado_piloto=date(2026, 9, 1), activacion_express=0, **base))
        express = ev(Metricas("B", "RENT", activado_piloto=date(2026, 9, 1), activacion_express=1, **base))
        vieja = ev(Metricas("C", "RENT", activado_piloto=date(2024, 9, 1), activacion_express=1, **base))
        self.assertLess(express["score_final"], normal["score_final"])
        self.assertLess(express["contribuciones"]["activacion_express"]["aporte"], vieja["contribuciones"]["activacion_express"]["aporte"])
        self.assertTrue(any("EXPRESS" in o for o in express["observaciones"]))

    def test_negativas_nunca_suman(self):
        r = ev(Metricas("L", "RENT", dias_antiguedad=400, n_finalizados=100, n_cancel_piloto=5))
        for v in ("suspension_piloto", "expulsion", "conducta_inapropiada"):
            self.assertEqual(r["contribuciones"][v]["aporte"], 0.0)


class DocumentosTest(unittest.TestCase):
    def test_documentos_restringen_o_alertan_sin_puntos(self):
        from score.engine import Documentos
        base = dict(n_finalizados=100, n_cancel_piloto=5)
        limpio = ev(Metricas("L", "RENT", **base))
        ok = ev(Metricas("A", "RENT", documentos=Documentos(licencia_estado="ACTIVA", licencia_vence=date(2030, 1, 1),
                                                          policia_pendientes=0, soat_vence=date(2027, 1, 1)), **base))
        self.assertEqual(ok["estado"], "OK"); self.assertEqual(ok["score_final"], limpio["score_final"])
        venc = ev(Metricas("B", "RENT", documentos=Documentos(licencia_estado="ACTIVA", soat_vence=date(2026, 3, 1)), **base))
        self.assertEqual(venc["estado"], "RESTRINGIDO"); self.assertEqual(venc["score_final"], limpio["score_final"])  # no toca el score
        self.assertTrue(any("SOAT vencido" in o for o in venc["observaciones"]))
        pol = ev(Metricas("C", "RENT", documentos=Documentos(policia_pendientes=1), **base))
        self.assertEqual(pol["estado"], "RESTRINGIDO")
        tec = ev(Metricas("D", "RENT", documentos=Documentos(tecno_vence=date(2026, 1, 1)), **base))
        self.assertEqual(tec["estado"], "OK"); self.assertTrue(any(a.startswith("doc: Tecnomec") for a in tec["alertas"]))
        pv = ev(Metricas("E", "RENT", documentos=Documentos(soat_vence=date(2026, 10, 1)), **base))
        self.assertEqual(pv["estado"], "OK"); self.assertTrue(any("SOAT vence" in o for o in pv["observaciones"]))
        nf = ev(Metricas("F", "RENT", documentos=Documentos(runt_mssg="No se encontró información de licencia en el RUNT."), **base))
        self.assertEqual(nf["estado"], "OK"); self.assertTrue(any("no se encontró" in a for a in nf["alertas"]))

    def test_flag_se_descarta_si_hay_historial(self):
        import tempfile, shutil
        d = Path(tempfile.mkdtemp())
        try:
            (d / "pilotos.csv").write_text("piloto_id,nombre,tipo,n_finalizados\nX,X,RENT,50\nY,Y,RENT,50\n")
            (d / "eventos.csv").write_text("piloto_id,tipo_evento,fecha,activo,severidad,origen\nX,suspension_piloto,2026-09-15,1,,flag\nY,suspension_piloto,2026-09-15,1,,flag\n")
            (d / "eventos_suspensiones.csv").write_text("piloto_id,tipo_evento,fecha,activo,severidad,origen\nX,suspension_piloto,2026-08-01,1,,historial\n")
            ms = {m.piloto_id: m for m in cargar_datos(d)}
            self.assertEqual(len(ms["X"].eventos), 1); self.assertEqual(ms["X"].eventos[0].fecha, date(2026, 8, 1))
            self.assertEqual(len(ms["Y"].eventos), 1)   # sin historial: el flag se conserva
        finally:
            shutil.rmtree(d)


class ConductaTest(unittest.TestCase):
    def test_conducta_confirmada_descuenta_moderado_y_en_los_tres_tipos(self):
        for tipo in TIPOS:
            base = dict(n_finalizados=100, n_cancel_piloto=5)
            limpio = ev(Metricas("L", tipo, **base))
            uno = ev(Metricas("1", tipo, eventos=[Evento("conducta_inapropiada", HOY, subtipo="ABUSIVE_LANGUAGE")], **base))
            cinco = ev(Metricas("5", tipo, eventos=[Evento("conducta_inapropiada", HOY)] * 5, **base))
            viejo = ev(Metricas("V", tipo, eventos=[Evento("conducta_inapropiada", date(2025, 3, 15))], **base))
            self.assertLess(uno["contribuciones"]["_bloques"]["score_sin_clip"], limpio["contribuciones"]["_bloques"]["score_sin_clip"], tipo)
            # moderado: un caso de hoy quita menos de 0.25 puntos
            self.assertGreater(uno["contribuciones"]["_bloques"]["score_sin_clip"], limpio["contribuciones"]["_bloques"]["score_sin_clip"] - 0.25, tipo)
            self.assertLess(cinco["score_final"], uno["score_final"], tipo)
            self.assertEqual(cinco["sub_scores"]["conducta_inapropiada"]["score"], 0.0, tipo)
            self.assertGreater(viejo["contribuciones"]["_bloques"]["score_sin_clip"], uno["contribuciones"]["_bloques"]["score_sin_clip"], tipo)   # decae
            self.assertEqual(uno["estado"], "OK", tipo)                          # no restringe
            self.assertTrue(any("Conducta inapropiada confirmada" in o for o in uno["observaciones"]), tipo)

    def test_severidad_por_subtipo(self):
        from copy import deepcopy
        P = deepcopy(PARAMS); P["eventos"]["conducta_inapropiada"]["severidad_por_subtipo"]["PROSTITUTION_FRAUD"] = 2.0
        base = dict(n_finalizados=100, n_cancel_piloto=5)
        a = evaluar(Metricas("A", "RENT", eventos=[Evento("conducta_inapropiada", HOY, subtipo="ABUSIVE_LANGUAGE")], **base), P, PESOS, REGLAS, HOY)
        b = evaluar(Metricas("B", "RENT", eventos=[Evento("conducta_inapropiada", HOY, subtipo="PROSTITUTION_FRAUD")], **base), P, PESOS, REGLAS, HOY)
        self.assertLess(b["score_final"], a["score_final"])


class CupoTest(unittest.TestCase):
    def test_cupo_por_score_y_compuertas(self):
        from score.engine import Recaudo
        base = dict(dias_antiguedad=600, n_finalizados=200, n_cancel_piloto=0, n_sin_novedad_a_tiempo=200)
        top = ev(Metricas("T", "B2B", n_alto_valor=40, n_alto_valor_ok=40, **base))
        self.assertEqual(top["cupo"]["tramo"], "MAXIMO"); self.assertIsNone(top["cupo"]["monto_max"])
        sin_ev = ev(Metricas("S", "B2B", n_alto_valor=3, n_alto_valor_ok=3, **base))          # excelente pero sin evidencia
        self.assertEqual(sin_ev["cupo"]["tramo"], "MUY_ALTO")
        nov = ev(Metricas("N", "B2B", n_alto_valor=40, n_alto_valor_ok=25, **base))           # novedades: baja un tramo
        self.assertLess(["SIN_CUPO", "MINIMO", "MEDIO", "ALTO", "MUY_ALTO", "MAXIMO"].index(nov["cupo"]["tramo"]), 4)
        deuda = ev(Metricas("D", "B2B", recaudos=[Recaudo(datetime(2026, 9, 1, 9))], **base))  # recaudo vencido
        self.assertEqual(deuda["cupo"]["tramo"], "SIN_CUPO")
        nuevo = ev(Metricas("V", "B2B", activado_piloto=date(2026, 9, 10), n_finalizados=10))
        self.assertEqual(nuevo["cupo"]["tramo"], "SIN_CUPO")
        prov = ev(Metricas("P", "B2B", dias_antiguedad=200, n_finalizados=10, n_sin_novedad_a_tiempo=10))
        self.assertIn(prov["cupo"]["tramo"], ("SIN_CUPO", "MINIMO"))
        blq = ev(Metricas("B", "B2B", reglas_activas=["imei_compartido"], **base))
        self.assertEqual(blq["cupo"]["tramo"], "SIN_CUPO")
        self.assertEqual(ev(Metricas("Z", "B2C"))["cupo"]["tramo"], "SIN_CUPO")               # sin score
        self.assertEqual(ev(Metricas("R", "RENT", dias_antiguedad=600, n_finalizados=200))["cupo"]["tramo"], "NO_APLICA")


class TiemposTest(unittest.TestCase):
    def test_cancelacion_usa_su_ventana_si_viene(self):
        base = dict(dias_antiguedad=400, n_finalizados=100, n_cancel_piloto=50)     # 90 d: 33 % (≈ referencia)
        sin_v = ev(Metricas("A", "RENT", **base))
        con_v = ev(Metricas("B", "RENT", vc_n_cancel_piloto=10, vc_n_finalizados=290, **base))   # 180 d: 3 %
        self.assertEqual(con_v["sub_scores"]["cancelacion_piloto"]["detalle"]["n"], 300)
        self.assertEqual(con_v["sub_scores"]["cancelacion_piloto"]["detalle"]["ventana_dias"], 180)
        self.assertGreaterEqual(con_v["score_final"], sin_v["score_final"])
        peor = ev(Metricas("C", "RENT", vc_n_cancel_piloto=250, vc_n_finalizados=50, **base))
        self.assertLess(peor["score_final"], sin_v["score_final"])

    def test_sin_novedades_ventana_anual(self):
        r = ev(Metricas("A", "B2B", dias_antiguedad=400, n_finalizados=50, n_sin_novedad_a_tiempo=20,
                        vn_n_finalizados=400, vn_n_sin_novedad_a_tiempo=390))
        d = r["sub_scores"]["sin_novedades"]["detalle"]
        self.assertEqual((d["x"], d["n"], d["ventana_dias"]), (390, 400, 365))
        self.assertGreater(r["contribuciones"]["sin_novedades"]["aporte"], 0)

    def test_conducta_desde_julio_sin_decaimiento(self):
        base = dict(dias_antiguedad=400, n_finalizados=100, n_cancel_piloto=5)
        antes = ev(Metricas("A", "RENT", eventos=[Evento("conducta_inapropiada", date(2026, 6, 15))], **base))
        jul = ev(Metricas("B", "RENT", eventos=[Evento("conducta_inapropiada", date(2026, 7, 2))], **base))
        hoy = ev(Metricas("C", "RENT", eventos=[Evento("conducta_inapropiada", HOY)], **base))
        self.assertEqual(antes["contribuciones"]["conducta_inapropiada"]["aporte"], 0.0)     # antes de julio no cuenta
        self.assertLess(jul["contribuciones"]["conducta_inapropiada"]["aporte"], 0)
        self.assertEqual(jul["contribuciones"]["conducta_inapropiada"]["aporte"], hoy["contribuciones"]["conducta_inapropiada"]["aporte"])  # sin decaimiento
