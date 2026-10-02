"""
Regresión con titulares reales de senales.json (2 de octubre de 2026).
Cada caso: (titular, empresas esperadas, fragmentos esperados en las etiquetas de eventos o None si no importa).
"""
from radar.analysis.entidades import EntidadesDetector
from radar.analysis.eventos import EventosDetector

CASOS = [
    ("Marval anunció proyecto urbano en Bogotá, Soho 26, con una inversión de $2,8 billones", [], ["Inversi"]),
    ("Win concretó alianza con DSports para ampliar oferta deportiva en su plataforma", [], ["Alianza"]),
    ("Opa, qué golazo", [], []),
    ("Gobierno sanciona ley de turismo", [], []),
    ("SIC sanciona a empresa por prácticas restrictivas", [], ["Investigaci"]),
    ("CNE abre investigación a campañas", [], []),
    ("Éxito de ventas del libro", [], []),
    ("Éxito reporta pérdida neta", ["Almacenes Éxito S.A."], ["Resultados"]),
    ("Isa lleva a su hijo al colegio", [], []),
    ("ISA adjudica proyecto", ["Interconexión Eléctrica S.A. E.S.P."], ["Licencia"]),
    ("Grupo Nutresa absorbió a Nugil y Jgdb con la totalidad de sus activos, pasivos y patrimonio", ["Grupo Nutresa S.A."], ["Integraci"]),
    ("ANLA otorga licencia a proyecto de petróleo de Ecopetrol en Meta", ["Ecopetrol S.A."], ["Licencia"]),
    ("La UPME adjudicó al Grupo Energía Bogotá importante proyecto para el abastecimiento de la Sabana de Bogotá", ["Grupo Energía Bogotá S.A. E.S.P."], ["Licencia"]),
    ("La UPME presentó el plan de expansión", [], []),
    ("Banco de Bogotá reporta utilidades", ["Banco de Bogotá S.A."], None),
    ("Grupo Gilinski lanza una OPA por Grupo Nutresa", ["Grupo Nutresa S.A."], ["OPA"]),
    ("El dólar en Colombia hoy: así abrió la jornada", [], []),
    ("El peso colombiano se devalúa frente al dólar", [], ["Movimiento"]),
]


def test_regresion_titulares_reales():
    ent, ev = EntidadesDetector(), EventosDetector()
    errores = []
    for titulo, empresas, etiquetas in CASOS:
        encontradas, _ = ent.detectar_empresas(titulo)
        if encontradas != empresas:
            errores.append(f"EMPRESAS {titulo!r}: esperado {empresas}, salió {encontradas}")
        if etiquetas is not None:
            sale = [m["etiqueta"] for m in ev.evaluar_texto(titulo)]
            falta = [x for x in etiquetas if not any(x.lower() in y.lower() for y in sale)]
            if falta or (not etiquetas and sale):
                errores.append(f"EVENTOS {titulo!r}: esperado {etiquetas}, salió {sale}")
    assert not errores, "\n".join(errores)


def test_limpieza_de_senales_obsoletas(tmp_path):
    """Una señal vieja que la lógica actual ya no genera se borra; la vigente y las de notas fuera del lote se conservan."""
    from radar.db import Database

    db = Database(str(tmp_path / "t.db"))
    base = {"tipo": "regulatorio", "etiqueta": "x", "empresas": [], "sectores": [], "medios": []}
    db.guardar_senal({**base, "senal_key": "vigente", "articulos_ids": [1]})
    db.guardar_senal({**base, "senal_key": "vieja", "articulos_ids": [1]})
    db.guardar_senal({**base, "senal_key": "fuera_del_lote", "articulos_ids": [1, 99]})
    borradas = db.eliminar_senales_obsoletas({1, 2}, {"vigente"})
    claves = {s["senal_key"] for s in db.obtener_senales_exportables()}
    assert borradas == 1
    assert claves == {"vigente", "fuera_del_lote"}
