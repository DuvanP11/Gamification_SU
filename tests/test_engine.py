# tests/test_engine.py — python3 -m unittest -v
import unittest
from datetime import date
from pathlib import Path
from score.engine import (rampa, tasa_ajustada, decaimiento, sub_score_evento, sub_score_volumen,
                          Metricas, Evento, evaluar, validar_pesos, TIPOS, EVENTOS)
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
                     eventos=[Evento(e, HOY) for e in EVENTOS for _ in range(5)])
        r = ev(m); self.assertEqual(r["score_final"], 0.0)
        # Todo al mejor
        m = Metricas("Y", "B2B", n_finalizados=500, n_cancel_piloto=0, n_sin_novedad_a_tiempo=500,
                     n_alto_valor=100, n_alto_valor_ok=100, n_res_cumplidas=50, n_res_incumplidas_atrib=0)
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
        # 1 de 4 (25 % crudo) NO se lee como 25 %: el prior lo amortigua
        self.assertGreater(r["sub_scores"]["cancelacion_piloto"]["detalle"]["tasa_ajustada"], 0.08)
        self.assertLess(r["sub_scores"]["cancelacion_piloto"]["detalle"]["tasa_ajustada"], 0.25)

    def test_no_aplica_sale_del_calculo(self):
        r = ev(Metricas("R", "RENT", n_finalizados=50))
        for v in ("alto_valor", "sin_novedades", "cumplimiento_reservas", "bloqueo_24h"):
            self.assertEqual(r["sub_scores"][v]["motivo"], "no_aplica")
            self.assertNotIn(v, r["contribuciones"])
        r = ev(Metricas("B", "B2B", n_finalizados=50))
        self.assertEqual(r["sub_scores"]["baneo_imei"]["motivo"], "no_aplica")

    def test_historial_limpio_no_suma(self):
        base = dict(n_finalizados=50, n_cancel_piloto=5, n_cancel_pasajero=30)
        limpio = ev(Metricas("A", "RENT", **base))
        self.assertEqual(limpio["contribuciones"]["_bloques"]["P_antecedentes"], 0.0)
        self.assertAlmostEqual(limpio["score_final"], round(limpio["contribuciones"]["_bloques"]["D_desempeno"], 1))

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

    def test_datos_ejemplo_cargan_y_estan_en_rango(self):
        for m in cargar_datos(RAIZ / "data"):
            r = ev(m)
            if r["score_final"] is not None:
                self.assertGreaterEqual(r["score_final"], 0.0); self.assertLessEqual(r["score_final"], 5.0)


if __name__ == "__main__":
    unittest.main()
