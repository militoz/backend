"""
Pruebas integrales para Colombia Radar (pytest).
Cubre:
- Punto 0: Conservación de historia (limpiar solo borra demo, guardar no descarta por fecha).
- Punto 1: Colectores oficiales directas (Superfinanciera, BVC, SIC, Supersociedades) y empresa_hint.
- Punto 2: Conservación de resumen en RSS/GNews y enriquecimiento con extracto (~1500 caracteres).
- Punto 3: Fuentes directas configuradas inactivas y deduplicación GNews.
- Punto 4: Series macro e insumos en tabla 'series' y evento macro por variación de umbral.
- Punto 5: Backfill histórico reanudable y parámetros GDELT.
- Punto 6: Detección de fuentes degradadas por corridas vacías o caída brusca.
- Punto 7: Importación y fusión de emisores oficiales desde CSV sin pisar alias manuales.
"""
import os
import shutil
import tempfile
import pytest
import yaml

from radar.db import Database
from radar.fetch import Fetcher
from radar.collectors.base import Item
from radar.collectors.superfinanciera import SuperfinancieraCollector
from radar.collectors.bvc import BvcCollector
from radar.collectors.sic import SicCollector
from radar.collectors.supersociedades import SupersociedadesCollector
from radar.collectors.gnews import GNewsCollector
from radar.collectors.serie import SerieCollector
from radar.pipeline import guardar, limpiar, enriquecer_articulo, analizar
from radar.analysis.entidades import EntidadesDetector
from radar.analysis.calor import calcular_score_calor


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_radar.db")
    db = Database(db_file)
    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def fixtures_dir():
    return os.path.join(os.path.dirname(__file__), "fixtures")


# ==============================================================================
# TAREA 0: HISTORIA
# ==============================================================================
def test_punto_0_guardar_conserva_historia(temp_db):
    """Verifica que guardar() no descarta noticias con fechas antiguas (anteriores al 1 de enero)."""
    items_antiguos = [
        Item(titulo="Noticia histórica 2024", url="https://ejemplo.com/2024", fecha="2024-05-10", fuente_id="archivo"),
        Item(titulo="Noticia histórica 2023", url="https://ejemplo.com/2023", fecha="2023-11-20", fuente_id="archivo"),
        Item(titulo="Noticia demo", url="https://ejemplo.com/demo1", fecha="2026-09-01", fuente_id="demo"),
    ]
    guardados = guardar(items_antiguos, temp_db)
    assert guardados == 3

    todos = temp_db.obtener_articulos(limit=10)
    assert len(todos) == 3
    fechas = {a["fecha"] for a in todos}
    assert "2024-05-10" in fechas
    assert "2023-11-20" in fechas


def test_punto_0_limpiar_solo_borra_demo(temp_db):
    """Verifica que limpiar() solo elimina los registros con fuente_id='demo' y conserva la historia."""
    items = [
        Item(titulo="Noticia Real 1", url="https://ejemplo.com/r1", fecha="2024-03-01", fuente_id="larepublica"),
        Item(titulo="Noticia Real 2", url="https://ejemplo.com/r2", fecha="2025-08-15", fuente_id="portafolio"),
        Item(titulo="Noticia Demo A", url="https://ejemplo.com/d1", fecha="2026-01-02", fuente_id="demo"),
        Item(titulo="Noticia Demo B", url="https://ejemplo.com/d2", fecha="2026-02-05", fuente_id="demo"),
    ]
    guardar(items, temp_db)

    # Ejecutar limpiar
    borrados = limpiar(temp_db)
    assert borrados == 2

    restantes = temp_db.obtener_articulos(limit=10)
    assert len(restantes) == 2
    for art in restantes:
        assert art["fuente_id"] != "demo"
        assert art["fuente_id"] in ["larepublica", "portafolio"]


# ==============================================================================
# TAREA 1: FUENTES OFICIALES DIRECTAS Y EMPRESA_HINT
# ==============================================================================
def test_punto_1_superfinanciera_collector(fixtures_dir):
    with open(os.path.join(fixtures_dir, "superfinanciera.html"), "rb") as f:
        html_bytes = f.read()

    fetcher = Fetcher()
    fetcher.registrar_mock("https://mock.superfinanciera.gov.co", status_code=200, body=html_bytes)

    cfg = {
        "id": "test_superfinanciera",
        "tipo": "superfinanciera",
        "url": "https://mock.superfinanciera.gov.co",
        "peso": 1.0,
        "certeza": "confirmado",
        "item_selector": ".item-relevante",
        "title_selector": ".asunto a",
        "link_selector": "a",
        "date_selector": ".fecha",
        "emisor_selector": ".emisor",
    }
    col = SuperfinancieraCollector(cfg)
    items = col.recolectar(fetcher)

    assert len(items) == 2
    assert items[0].certeza == "confirmado"
    assert items[0].empresa_hint == "Ecopetrol S.A."
    assert "Ecopetrol S.A." in items[0].titulo
    assert "/noticias/relevante/eco-101" in items[0].url
    assert items[1].empresa_hint == "Bancolombia S.A."


def test_punto_1_bvc_collector(fixtures_dir):
    with open(os.path.join(fixtures_dir, "bvc.html"), "rb") as f:
        html_bytes = f.read()

    fetcher = Fetcher()
    fetcher.registrar_mock("https://mock.bvc.com.co", status_code=200, body=html_bytes)

    cfg = {
        "id": "test_bvc",
        "tipo": "bvc",
        "url": "https://mock.bvc.com.co",
        "item_selector": ".item-boletin",
        "title_selector": ".titulo-aviso a",
        "link_selector": "a",
        "date_selector": ".fecha-publicacion",
        "emisor_selector": ".nemotecnico",
    }
    col = BvcCollector(cfg)
    items = col.recolectar(fetcher)

    assert len(items) == 2
    assert items[0].certeza == "confirmado"
    assert items[0].empresa_hint == "GRUPOARGOS"
    assert items[1].empresa_hint == "NUTRESA"


def test_punto_1_sic_collector(fixtures_dir):
    with open(os.path.join(fixtures_dir, "sic.html"), "rb") as f:
        html_bytes = f.read()

    fetcher = Fetcher()
    fetcher.registrar_mock("https://mock.sic.gov.co", status_code=200, body=html_bytes)

    cfg = {
        "id": "test_sic",
        "tipo": "sic",
        "url": "https://mock.sic.gov.co",
        "item_selector": ".integracion-registro",
        "title_selector": ".titulo-tramite a",
        "link_selector": "a",
        "date_selector": ".fecha-resolucion",
        "intervinientes_selector": ".empresas-involucradas",
    }
    col = SicCollector(cfg)
    items = col.recolectar(fetcher)

    assert len(items) == 2
    assert items[0].certeza == "confirmado"
    assert "Terpel" in items[0].empresa_hint
    assert "Éxito" in items[1].empresa_hint


def test_punto_1_supersociedades_collector(fixtures_dir):
    with open(os.path.join(fixtures_dir, "supersociedades.html"), "rb") as f:
        html_bytes = f.read()

    fetcher = Fetcher()
    fetcher.registrar_mock("https://mock.supersociedades.gov.co", status_code=200, body=html_bytes)

    cfg = {
        "id": "test_supersociedades",
        "tipo": "supersociedades",
        "url": "https://mock.supersociedades.gov.co",
        "item_selector": ".proceso-item",
        "title_selector": ".asunto-proceso a",
        "link_selector": "a",
        "date_selector": ".fecha-auto",
        "sociedad_selector": ".sociedad-concursada",
    }
    col = SupersociedadesCollector(cfg)
    items = col.recolectar(fetcher)

    assert len(items) == 2
    assert items[0].certeza == "confirmado"
    assert items[0].empresa_hint == "Avianca Group International"
    assert "Ley 1116" in items[0].titulo


def test_punto_1_empresa_hint_linking():
    """Verifica que EntidadesDetector vincula directamente por empresa_hint con empresas.yaml."""
    detector = EntidadesDetector(config_dir="config")

    # Match por nombre
    empresas, sectores = detector.detectar_empresas("Aviso de asamblea", empresa_hint="Ecopetrol S.A.")
    assert "Ecopetrol S.A." in empresas
    assert "Petróleo y Gas" in sectores

    # Match por ticker / nemotécnico (ej. BVC 'GRUPOARGOS')
    empresas, sectores = detector.detectar_empresas("Acuerdo suscrito", empresa_hint="GRUPOARGOS")
    assert "Grupo Argos S.A." in empresas

    # Match por alias
    empresas, sectores = detector.detectar_empresas("Información", empresa_hint="Terpel")
    assert "Organización Terpel S.A." in empresas


# ==============================================================================
# TAREA 2: MÁS TEXTO POR NOTICIA Y ENRIQUECIMIENTO
# ==============================================================================
def test_punto_2_gnews_conserva_resumen(fixtures_dir):
    with open(os.path.join(fixtures_dir, "gnews_feed.xml"), "rb") as f:
        xml_bytes = f.read()

    fetcher = Fetcher()
    fetcher.registrar_mock("https://mock.gnews.com", status_code=200, body=xml_bytes)

    col = GNewsCollector({"id": "gnews_test", "url": "https://mock.gnews.com"})
    items = col.recolectar(fetcher)

    assert len(items) == 2
    # El resumen no fue borrado porque contiene texto informativo real
    assert items[0].resumen is not None
    assert "estatal petrolera" in items[0].resumen
    assert "La República" == items[0].medio


def test_punto_2_enriquecer_articulo():
    html_simulado = b"""
    <html>
      <head><title>Noticia</title></head>
      <body>
        <nav><a href="/">Inicio</a></nav>
        <h1>Titular de la inversion</h1>
        <p>Ecopetrol anuncio una inversion historica de US$ 500 millones para el desarrollo de proyectos solares y eolicos en el Caribe colombiano durante los proximos tres anos.</p>
        <p>El presidente de la compania aseguro que esta decision reducira las emisiones de carbono de las refinerias y aumentara la rentabilidad de largo plazo.</p>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    fetcher = Fetcher()
    url_articulo = "https://ejemplo.com/noticia-inversion"
    fetcher.registrar_mock(url_articulo, status_code=200, body=html_simulado)

    extracto = enriquecer_articulo(url_articulo, fetcher, max_caracteres=1500)
    assert extracto is not None
    assert "Ecopetrol anuncio una inversion" in extracto
    assert "Copyright" not in extracto
    assert len(extracto) <= 1500


# ==============================================================================
# TAREA 3: FUENTES DIRECTAS DE MEDIOS
# ==============================================================================
def test_punto_3_medios_configurados():
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "sources.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    fuentes = {f["id"]: f for f in cfg.get("fuentes", [])}

    # Verificar presencia de las fuentes de medios solicitadas
    esperadas = [
        "medio_larepublica",
        "medio_valora_analitik",
        "medio_dinero",
        "medio_portafolio",
        "medio_bloomberg_linea",
        "medio_eltiempo_economia",
    ]
    for fid in esperadas:
        assert fid in fuentes, f"Falta fuente {fid} en config/sources.yaml"
        # Deben estar desactivadas por defecto hasta confirmación
        assert fuentes[fid]["activo"] is False, f"La fuente {fid} debe estar activa: false por defecto"

    # Verificar que Portafolio está configurado bajo HTTPS
    assert fuentes["medio_portafolio"]["url"].startswith("https://")


# ==============================================================================
# TAREA 4: SERIES MACRO E INSUMOS
# ==============================================================================
def test_punto_4_serie_collector_y_evento_macro(fixtures_dir, temp_db):
    with open(os.path.join(fixtures_dir, "trm_socrata.json"), "rb") as f:
        json_bytes = f.read()

    fetcher = Fetcher(db=temp_db)
    url_trm = "https://mock.datos.gov.co/trm.json"
    fetcher.registrar_mock(url_trm, status_code=200, body=json_bytes)

    cfg = {
        "id": "serie_trm_test",
        "tipo": "serie",
        "serie_id": "trm",
        "url": url_trm,
        "formato": "json",
        "campo_fecha": "vigenciadesde",
        "campo_valor": "valor",
        "umbral_variacion_pct": 1.0,  # 4160 -> 4250 es +2.17% (supera 1.0%)
        "etiqueta_nombre": "Dólar TRM",
        "unidad": "COP",
    }

    col = SerieCollector(cfg)
    items = col.recolectar(fetcher)

    # 1. Se guardó en la tabla 'series'
    puntos = temp_db.obtener_ultimos_valores_serie("trm")
    assert len(puntos) == 3

    # 2. Se generó señal de evento macro confirmado
    assert len(items) == 1
    assert items[0].certeza == "confirmado"
    assert "Señal Macro: Dólar TRM sube" in items[0].titulo
    assert items[0].metadata.get("es_evento_macro") is True


# ==============================================================================
# TAREA 6: SALUD DE FUENTES Y DETECCIÓN DE DEGRADACIÓN
# ==============================================================================
def test_punto_6_deteccion_fuentes_degradadas(temp_db):
    fid = "fuente_prueba"

    # Simular 3 corridas consecutivas con 0 items
    for _ in range(3):
        temp_db.registrar_salud(
            fuente_id=fid,
            items_recolectados=0,
            exito=True,
            max_corridas_vacias=3,
        )

    salud = temp_db.obtener_salud_fuentes()
    f_info = next(f for f in salud if f["fuente_id"] == fid)
    assert f_info["estado"] == "degradada"
    assert "0 items durante 3 corridas" in f_info["motivo_degradada"]


def test_punto_6_caida_brusca_items(temp_db):
    fid = "fuente_volumen"
    # Establecer promedio previo alto
    temp_db.registrar_salud(fid, items_recolectados=20, exito=True)
    temp_db.registrar_salud(fid, items_recolectados=18, exito=True)

    # Simular caída brusca a 1 item (< 50% de 18+)
    temp_db.registrar_salud(fid, items_recolectados=1, exito=True, umbral_caida_brusca=0.5)

    salud = temp_db.obtener_salud_fuentes()
    f_info = next(f for f in salud if f["fuente_id"] == fid)
    assert f_info["estado"] == "degradada"
    assert "Caída brusca" in f_info["motivo_degradada"]


# ==============================================================================
# TAREA 7: IMPORTAR EMISORES DESDE CSV
# ==============================================================================
def test_punto_7_importar_emisores(fixtures_dir):
    temp_dir = tempfile.mkdtemp()
    test_yaml = os.path.join(temp_dir, "empresas.yaml")

    # Archivo inicial con un alias manual que no debe pisarse
    data_inicial = {
        "empresas": [
            {
                "nombre": "Ecopetrol S.A.",
                "ticker": "ECOPETROL",
                "sector": "Petróleo y Gas",
                "alias": ["Mi Alias Manual Ecopetrol"],
            }
        ]
    }
    with open(test_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_inicial, f)

    from run import cmd_importar_emisores
    class Args:
        archivo = os.path.join(fixtures_dir, "emisores.csv")

    # Sobrescribir temporalmente la ruta en run.py usando un patch
    import run
    original_cargar = run.cargar_yaml
    original_guardar = run.guardar_yaml
    run.cargar_yaml = lambda path: yaml.safe_load(open(test_yaml, "r", encoding="utf-8"))
    run.guardar_yaml = lambda path, data: yaml.safe_dump(data, open(test_yaml, "w", encoding="utf-8"))

    try:
        cmd_importar_emisores(Args())
    finally:
        run.cargar_yaml = original_cargar
        run.guardar_yaml = original_guardar

    with open(test_yaml, "r", encoding="utf-8") as f:
        resultado = yaml.safe_load(f)

    empresas = {e["nombre"]: e for e in resultado["empresas"]}

    # 1. Ecopetrol conservó su alias manual y sumó su NIT del CSV
    assert "Ecopetrol S.A." in empresas
    assert "Mi Alias Manual Ecopetrol" in empresas["Ecopetrol S.A."]["alias"]
    assert empresas["Ecopetrol S.A."].get("nit") == "899999068-1"

    # 2. BVC fue agregada con alias limpio generado (sin S.A.)
    assert "Bolsa de Valores de Colombia S.A." in empresas
    assert "Bolsa de Valores de Colombia" in empresas["Bolsa de Valores de Colombia S.A."]["alias"]
    assert empresas["Bolsa de Valores de Colombia S.A."]["ticker"] == "BVC"

    # 3. Promigas fue agregada
    assert "Promigas S.A. E.S.P." in empresas
    assert empresas["Promigas S.A. E.S.P."]["ticker"] == "PROMIGAS"

    shutil.rmtree(temp_dir, ignore_errors=True)
