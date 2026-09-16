# data/generar_datos_ficticios.py — regenera los CSV de ejemplo (determinista).
# Mantiene los 11 casos con nombre (P001–P011) y agrega ~40 pilotos por tipo
# para que el ranking top/medio/peores tenga con qué llenarse.
#   python3 data/generar_datos_ficticios.py
import csv, random
from datetime import date, datetime, timedelta
from pathlib import Path

HOY = date(2026, 9, 15)
R = random.Random(20260915)
D = Path(__file__).resolve().parent

def oid(n):  # id estilo Mongo ObjectId, determinista
    return "%024x" % R.getrandbits(96)

def fecha_hace(dias): return (HOY - timedelta(days=dias)).isoformat()

COLS = ["piloto_id","nombre","caso","tipo","driver_id","passenger_id","activado_piloto","activado_pasajero",
        "calif_gamification","calif_app","activacion_express",
        "vc_n_cancel_piloto","vc_n_finalizados","vc_n_otros_atribuibles","vc_n_no_atribuibles","vn_n_finalizados","vn_n_sin_novedad_a_tiempo","dias_antiguedad","n_finalizados","n_cancel_piloto","n_cancel_pasajero",
        "n_cancel_plataforma","n_otros_atribuibles","n_sin_novedad_a_tiempo","n_alto_valor","n_alto_valor_ok",
        "n_res_cumplidas","n_res_incumplidas_atrib","n_res_cancel_atrib","n_res_no_atrib",
        "n_calificados","suma_calificaciones"]

# ── los 11 casos con nombre (idénticos a la v0.1, con las columnas nuevas) ──
NOMBRADOS = [
 dict(piloto_id="P001",caso="buen comportamiento sostenido",nombre="Ana María Restrepo",tipo="B2B",dias_antiguedad=900,n_finalizados=180,n_cancel_piloto=3,n_cancel_pasajero=12,n_cancel_plataforma=1,n_sin_novedad_a_tiempo=172,n_alto_valor=25,n_alto_valor_ok=25,n_res_cumplidas=30,n_res_incumplidas_atrib=1,n_res_cancel_atrib=0,n_res_no_atrib=2),
 dict(piloto_id="P002",caso="piloto nuevo (12 días), pocos servicios, activación express",nombre="Bruno Cárdenas",tipo="RENT",dias_antiguedad=12,activacion_express=1,n_finalizados=6,n_cancel_piloto=1,n_cancel_pasajero=2),
 dict(piloto_id="P003",caso="suspensión antigua + muchas finalizaciones",nombre="Carla Jiménez",tipo="RENT",dias_antiguedad=1500,n_finalizados=400,n_cancel_piloto=10,n_cancel_pasajero=60,n_cancel_plataforma=2),
 dict(piloto_id="P004",caso="comportamiento negativo reciente",nombre="Diego Salazar",tipo="B2C",dias_antiguedad=400,n_finalizados=40,n_cancel_piloto=9,n_cancel_pasajero=5,n_otros_atribuibles=1,n_sin_novedad_a_tiempo=30,n_alto_valor=8,n_alto_valor_ok=5),
 dict(piloto_id="P005",caso="alto valor con muchas novedades",nombre="Elena Quintero",tipo="B2B",dias_antiguedad=700,n_finalizados=90,n_cancel_piloto=2,n_cancel_pasajero=6,n_sin_novedad_a_tiempo=70,n_alto_valor=40,n_alto_valor_ok=28,n_res_cumplidas=10,n_res_incumplidas_atrib=4,n_res_cancel_atrib=0,n_res_no_atrib=1),
 dict(piloto_id="P006",caso="múltiples suspensiones + IMEI baneado",nombre="Fabián Ospina",tipo="RENT",dias_antiguedad=800,n_finalizados=120,n_cancel_piloto=20,n_cancel_pasajero=15,n_cancel_plataforma=1,n_otros_atribuibles=2),
 dict(piloto_id="P007",caso="piloto nuevo (3 días) con cero servicios: arranca en 0.0",nombre="Gloria Arango",tipo="B2C",dias_antiguedad=3),
 dict(piloto_id="P008",caso="expulsión histórica (reintegrado)",nombre="Hugo Betancur",tipo="B2B",dias_antiguedad=1100,n_finalizados=50,n_cancel_piloto=6,n_cancel_pasajero=4,n_sin_novedad_a_tiempo=46,n_alto_valor=4,n_alto_valor_ok=4,n_res_cumplidas=8,n_res_incumplidas_atrib=0,n_res_cancel_atrib=1,n_res_no_atrib=0),
 dict(piloto_id="P009",caso="una sola cancelación",nombre="Iván Zapata",tipo="RENT",dias_antiguedad=600,n_finalizados=100,n_cancel_piloto=1,n_cancel_pasajero=10),
 dict(piloto_id="P010",caso="muchos servicios de alto valor bien atendidos",nombre="Julia Moreno",tipo="B2C",dias_antiguedad=950,n_finalizados=200,n_cancel_piloto=4,n_cancel_pasajero=9,n_sin_novedad_a_tiempo=195,n_alto_valor=60,n_alto_valor_ok=59),
 dict(piloto_id="P011",caso="cuenta nueva con tope por regla",nombre="Kevin Patiño",tipo="B2B",dias_antiguedad=20,n_finalizados=25,n_cancel_piloto=0,n_cancel_pasajero=1,n_sin_novedad_a_tiempo=24,n_alto_valor=2,n_alto_valor_ok=2,n_res_cumplidas=5,n_res_incumplidas_atrib=0,n_res_cancel_atrib=0,n_res_no_atrib=0),
 dict(piloto_id="P012",caso="recaudos pagados tarde y uno vencido",nombre="Laura Henao",tipo="B2B",dias_antiguedad=500,n_finalizados=80,n_cancel_piloto=3,n_cancel_pasajero=5,n_sin_novedad_a_tiempo=76,n_alto_valor=10,n_alto_valor_ok=10,n_res_cumplidas=12,n_res_incumplidas_atrib=1,n_res_cancel_atrib=0,n_res_no_atrib=0),
]
EVENTOS = [("P003","suspension_piloto","2025-01-20",0),("P004","suspension_piloto","2026-09-05",0),("P004","invitacion_pibox","2026-08-26",0),
           ("P006","suspension_piloto","2026-08-16",0),("P006","suspension_piloto","2026-06-17",0),("P006","suspension_piloto","2026-02-27",0),
           ("P006","baneo_imei","2026-09-01",1),("P008","expulsion","2025-08-11",0),("P008","invitacion_rent","2024-03-01",0),("P011","suspension_pasajero","2026-07-01",0)]
# recaudos: (piloto, fecha_recaudo, fecha_abono|None)
RECAUDOS = [("P011","2026-09-10 10:00:00","2026-09-10 18:30:00"),            # a tiempo
            ("P012","2026-09-04 17:00:00","2026-09-07 15:00:00"),            # viernes → lunes: 22 h hábiles, a tiempo
            ("P012","2026-08-20 09:00:00","2026-08-22 12:00:00"),            # 51 h hábiles: tarde
            ("P012","2026-08-25 09:00:00","2026-08-27 09:00:00"),            # 48 h: tarde
            ("P012","2026-09-08 09:00:00",None),                             # vencido sin pagar
            ("P001","2026-08-30 11:00:00","2026-08-31 09:00:00"),            # a tiempo
            ("P001","2026-09-15 10:00:00",None)]                             # pendiente pero en plazo
REGLAS = [("P008","cancelaciones_en_racha"),("P011","cuenta_nueva_retiro_alto"),("P006","imei_compartido")]

NOMBRES = ["Andrés","Beatriz","Camilo","Daniela","Esteban","Fernanda","Gustavo","Helena","Ignacio","Juliana","Kevin","Lorena","Mateo","Natalia",
           "Óscar","Paola","Ramiro","Sofía","Tomás","Valeria","Wilson","Ximena","Yeison","Zulma","Alejandro","Brenda","César","Diana","Edwin","Flor"]
APELL = ["García","Rodríguez","Martínez","López","González","Pérez","Sánchez","Ramírez","Torres","Flores","Rivera","Gómez","Díaz","Cruz","Morales","Ortiz","Vargas","Castro","Rojas","Mendoza"]

def contexto(row, tipo):
    ant = row.get("dias_antiguedad") or R.randint(30, 1800)
    row.setdefault("dias_antiguedad", ant)
    row["driver_id"] = oid(0); row["passenger_id"] = oid(0)
    row["activado_pasajero"] = fecha_hace(ant + R.randint(0, 200))
    row["activado_piloto"] = fecha_hace(ant)
    row["calif_gamification"] = round(R.uniform(2.5, 5.0), 2)
    row["calif_app"] = round(R.uniform(3.5, 5.0), 2)
    if "activacion_express" not in row: row["activacion_express"] = 1 if R.random() < 0.15 else 0
    return row

filas = [contexto(dict(r), r["tipo"]) for r in NOMBRADOS]
eventos = [dict(piloto_id=p, tipo_evento=t, fecha=f, activo=a, severidad="") for p, t, f, a in EVENTOS]
recaudos = [dict(piloto_id=p, fecha_recaudo=fr, fecha_abono=fa or "") for p, fr, fa in RECAUDOS]
reglas = [dict(piloto_id=p, regla=r) for p, r in REGLAS]

n = 100
for tipo in ("B2B", "RENT", "B2C"):
    for _ in range(40):
        n += 1; pid = f"P{n:03d}"
        calidad = R.betavariate(4, 1.6)               # 0..1, sesgado a bueno
        fin = int(R.lognormvariate(3.6, 0.8)); fin = max(1, min(fin, 600))
        cp = int(fin * max(0, R.gauss(0.25 * (1 - calidad), 0.05)))
        row = dict(piloto_id=pid, nombre=f"{R.choice(NOMBRES)} {R.choice(APELL)}", tipo=tipo,
                   n_finalizados=fin, n_cancel_piloto=cp, n_cancel_pasajero=int(fin * R.uniform(0, 0.25)),
                   n_cancel_plataforma=int(fin * R.uniform(0, 0.03)), n_otros_atribuibles=0)
        if tipo in ("B2B", "B2C"):
            row["n_sin_novedad_a_tiempo"] = int(fin * min(1, max(0.5, R.gauss(0.75 + 0.25 * calidad, 0.05))))
            av = int(fin * R.uniform(0, 0.35)); row["n_alto_valor"] = av
            row["n_alto_valor_ok"] = int(av * min(1, max(0.4, R.gauss(0.7 + 0.3 * calidad, 0.08))))
        if tipo == "B2B":
            res = R.randint(0, 30); cum = int(res * min(1, max(0.5, R.gauss(0.75 + 0.25 * calidad, 0.08))))
            row.update(n_res_cumplidas=cum, n_res_incumplidas_atrib=res - cum, n_res_cancel_atrib=0, n_res_no_atrib=R.randint(0, 4))
            for _ in range(R.choice([0, 0, 0, 1, 1, 2, 3])):
                fr = datetime(2026, R.choice([7, 8, 9]), R.randint(1, 28), R.randint(7, 20))
                if fr.date() > HOY: fr = fr.replace(month=8)
                pago = R.random() < 0.55 + 0.4 * calidad
                fa = fr + timedelta(hours=R.uniform(2, 60)) if pago else None
                recaudos.append(dict(piloto_id=pid, fecha_recaudo=fr.strftime("%Y-%m-%d %H:%M:%S"), fecha_abono=fa.strftime("%Y-%m-%d %H:%M:%S") if fa else ""))
        # antecedentes: peor calidad → más eventos y más recientes
        for _ in range(int(R.expovariate(1 / (2.5 * (1 - calidad) + 0.05)))):
            te = R.choice(["suspension_piloto", "suspension_piloto", "invitacion_pibox", "invitacion_rent", "suspension_pasajero", "expulsion"] + (["baneo_imei"] if tipo == "RENT" else []))
            eventos.append(dict(piloto_id=pid, tipo_evento=te, fecha=fecha_hace(R.randint(3, 700)), activo=0, severidad=""))
        if R.random() < 0.05: reglas.append(dict(piloto_id=pid, regla=R.choice(["cancelaciones_en_racha", "fake_gps", "cuenta_nueva_retiro_alto"])))
        filas.append(contexto(row, tipo))

# Ventanas propias (manejo de tiempos): cancelación a 6 meses y novedades a 1 año, derivadas
# de los conteos de 90 días con un factor según la antigüedad. RNG aparte.
R3 = random.Random(11)
for row in filas:
    ant = row.get("dias_antiguedad") or 0
    f6 = min(2.0, max(1.0, ant / 90)); f12 = min(4.0, max(1.0, ant / 90))
    fin = int(row.get("n_finalizados") or 0); cp = int(row.get("n_cancel_piloto") or 0)
    row["vc_n_cancel_piloto"] = int(cp * f6 * R3.uniform(0.8, 1.2)); row["vc_n_finalizados"] = int(fin * f6 * R3.uniform(0.9, 1.1))
    row["vc_n_otros_atribuibles"] = 0; row["vc_n_no_atribuibles"] = int((int(row.get("n_cancel_pasajero") or 0)) * f6)
    if row.get("n_sin_novedad_a_tiempo") not in (None, ""):
        vnf = int(fin * f12 * R3.uniform(0.9, 1.1)); row["vn_n_finalizados"] = vnf
        row["vn_n_sin_novedad_a_tiempo"] = min(vnf, int(int(row["n_sin_novedad_a_tiempo"]) * f12 * R3.uniform(0.95, 1.05)))

# Conducta inapropiada confirmada: RNG aparte para no mover el resto de los datos.
R2 = random.Random(7)
for row in filas:
    if row["piloto_id"] in ("P004",) or (row["piloto_id"] > "P100" and R2.random() < 0.06):
        for _ in range(R2.choice([1, 1, 1, 2, 3])):
            eventos.append(dict(piloto_id=row["piloto_id"], tipo_evento="conducta_inapropiada", fecha=fecha_hace(R2.randint(5, 75)), activo=0, severidad="",
                                subtipo=R2.choice(["ABUSIVE_LANGUAGE", "ABUSIVE_LANGUAGE", "PROSTITUTION_FRAUD"])))

# Calificación del pasajero (2026-09-16): notas 1–5 en finalizados de 180 d. RNG aparte.
# Los casos con nombre llevan un promedio a mano para que se vean los tres lados de la referencia.
R4 = random.Random(16)
CALIF_NOMBRADOS = {"P001": 4.96, "P003": 4.90, "P004": 4.10, "P005": 4.70, "P006": 4.35, "P009": 4.85, "P010": 4.97, "P012": 4.80}
for row in filas:
    fin = int(row.get("vc_n_finalizados") or row.get("n_finalizados") or 0)
    if fin == 0:
        continue
    n_cal = int(fin * R4.uniform(0.45, 0.65))              # ~55 % de los finalizados traen nota (dato real)
    if n_cal == 0:
        continue
    prom = CALIF_NOMBRADOS.get(row["piloto_id"]) or min(5.0, max(3.6, R4.gauss(4.80, 0.18)))
    row["n_calificados"] = n_cal
    row["suma_calificaciones"] = int(round(prom * n_cal))

# Recaudos completos (2026-09-16): a los episodios ya definidos se les pone booking, monto y
# fecha_saldado (= abono, salvo los casos marcados), y se agregan recaudos abonados EN EL
# MOMENTO, que antes no se exportaban y son los que suman en recaudo_entregado.
R5 = random.Random(9)
for i, rc in enumerate(recaudos):
    rc["booking_id"] = "%024x" % R5.getrandbits(96)
    rc["monto"] = R5.choice([35000, 48000, 62000, 85000, 120000, 150000, 210000])
    rc["fecha_saldado"] = rc["fecha_abono"]
por_piloto = {}
for rc in recaudos:
    por_piloto.setdefault(rc["piloto_id"], []).append(rc)
# P012 (recaudos tarde y uno vencido): el vencido queda sin saldar → "no pago".
# P001 (buen comportamiento): además 6 recaudos abonados en el momento → entrega bien.
# P010 (B2C ejemplar): 5 recaudos en el momento. P004 (negativo reciente, B2C): 1 en el momento y 2 sin saldar.
EXTRA = {"P001": (6, 0), "P010": (5, 0), "P004": (1, 2), "P005": (3, 1)}
for row in filas:
    pid = row["piloto_id"]
    if row["tipo"] not in ("B2B", "B2C"):
        continue
    en_momento, sin_pagar = EXTRA.get(pid, (0, 0))
    if pid > "P100" and R5.random() < 0.5:
        en_momento = R5.randint(1, 8); sin_pagar = 1 if R5.random() < 0.12 else 0
    for k in range(en_momento + sin_pagar):
        fr = datetime(2026, R5.choice([7, 8]), R5.randint(1, 28), R5.randint(7, 20), R5.randint(0, 59))
        pagado = k < en_momento
        fa = (fr + timedelta(seconds=R5.randint(5, 50))).strftime("%Y-%m-%d %H:%M:%S") if pagado else ""
        recaudos.append(dict(piloto_id=pid, booking_id="%024x" % R5.getrandbits(96), fecha_recaudo=fr.strftime("%Y-%m-%d %H:%M:%S"),
                             monto=R5.choice([35000, 48000, 62000, 85000, 120000, 150000, 210000]), fecha_abono=fa, fecha_saldado=fa))

def escribir(nombre, cols, rows):
    with open(D / nombre, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})

escribir("pilotos.csv", COLS, filas)
escribir("eventos.csv", ["piloto_id", "tipo_evento", "fecha", "activo", "severidad", "subtipo"], eventos)
escribir("recaudos.csv", ["piloto_id", "booking_id", "fecha_recaudo", "monto", "fecha_abono", "fecha_saldado"], recaudos)
escribir("reglas_activas.csv", ["piloto_id", "regla"], reglas)
print(f"{len(filas)} pilotos, {len(eventos)} eventos, {len(recaudos)} recaudos, {len(reglas)} reglas")
