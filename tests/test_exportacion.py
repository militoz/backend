"""
Pruebas de las etapas 1 a 3: señales con artículos reales, ID estable, certeza declarada,
exportación a JSON, bloqueos visibles y base pública sin texto de medios.
"""
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone

import pytest

from radar.analysis.calor import calcular_score_calor, desglosar_score
from radar.collectors.base import Item
from radar.db import Database
from radar.export import (
    construir_macro,
    construir_salud,
    construir_senales,
    exportar,
    exportar_base_publica,
)
from radar.fetch import Fetcher
from radar.pipeline import analizar, evaluar_estricto, guardar, recolectar
from radar.util import normalizar_fecha, semana_iso

CFG = {
    "fuentes": [
        {"id": "bvc_hechos_relevantes", "nombre": "BVC - Hechos Relevantes", "tipo": "bvc", "certeza": "confirmado"},
        {"id": "gnews_empresas", "nombre": "Google News", "tipo": "gnews", "certeza": "probable"},
        {"id": "medio_larepublica", "nombre": "La República", "tipo": "rss", "medio": "La República", "certeza": "probable"},
    ]
}
AHORA = datetime(2026, 10, 1, 12, 0, 0)


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db = Database(os.path.join(temp_dir, "t.db"))
    db.temp_dir = temp_dir
    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


def _items_ecopetrol():
    return [
        Item(
            titulo="Ecopetrol cierra adquisición de participación en bloques del Permian",
            url="https://www.larepublica.co/empresas/ecopetrol-permian",
            fecha="Tue, 29 Sep 2026 18:40:00 GMT",
            resumen="Texto del medio que no debe publicarse",
            fuente_id="medio_larepublica",
            certeza="probable",
        ),
        Item(
            titulo="Ecopetrol anuncia adquisición de activos en Estados Unidos",
            url="https://news.google.com/rss/articles/CBMiXYZ",
            fecha="Wed, 30 Sep 2026 11:30:00 GMT",
            fuente_id="gnews_empresas",
            certeza="probable",
            medio="Valora Analitik",
        ),
    ]


# ---------------------------------------------------------------- fechas
def test_normalizar_fecha_formatos_y_basura():
    assert normalizar_fecha("Tue, 29 Sep 2026 18:40:00 GMT") == "2026-09-29T18:40:00Z"
    assert normalizar_fecha("2026-09-30T14:15:00Z") == "2026-09-30T14:15:00Z"
    assert normalizar_fecha("2026-09-30") == "2026-09-30T00:00:00Z"
    assert normalizar_fecha("hace dos horas") is None
    assert normalizar_fecha("") is None
    assert normalizar_fecha(None) is None
    assert semana_iso("2026-09-30T14:15:00Z") == "2026-w40"


# ---------------------------------------------------------------- score
def test_score_desglose_coincide_con_la_formula():
    d = desglosar_score(1.45, "confirmado", 3, "2026-09-30", ahora=AHORA)
    esperado = 1.45 * 1.4 * (0.9 + 0.3) * (d["pesoRecencia"] / 1.5)
    assert d["score"] == round(esperado, 2)
    assert d["pesoCerteza"] == 1.4 and d["pesoFuente"] == 1.2
    assert d["fechaDesconocida"] is False and d["certezaDesconocida"] is False
    assert calcular_score_calor(1.45, "confirmado", 3, "2026-09-30") >= 0


def test_score_marca_datos_desconocidos():
    d = desglosar_score(1.0, "inventada", 1, "", ahora=AHORA)
    assert d["fechaDesconocida"] is True and d["certezaDesconocida"] is True


# ---------------------------------------------------------------- señales estables
def test_senales_tienen_id_estable_y_no_se_duplican(temp_db):
    guardar(_items_ecopetrol(), temp_db)
    primera = analizar(temp_db, CFG, ahora=AHORA)
    assert primera, "debió detectar al menos una señal"
    claves_1 = sorted(s["senal_key"] for s in primera)
    ids_cluster_1 = sorted(s["cluster_id"] for s in primera)

    # Segunda y tercera corrida sin datos nuevos: mismas señales, mismos IDs
    analizar(temp_db, CFG, ahora=AHORA)
    segunda = analizar(temp_db, CFG, ahora=AHORA)
    assert sorted(s["senal_key"] for s in segunda) == claves_1
    assert sorted(s["cluster_id"] for s in segunda) == ids_cluster_1
    assert len(temp_db.obtener_senales_exportables()) == len(claves_1)


def test_nueva_nota_actualiza_la_misma_senal(temp_db):
    guardar(_items_ecopetrol(), temp_db)
    antes = {s["senal_key"]: s for s in analizar(temp_db, CFG, ahora=AHORA)}

    guardar(
        [
            Item(
                titulo="Portafolio: radiografía de la adquisición de Ecopetrol en Permian",
                url="https://www.portafolio.co/negocios/ecopetrol-permian",
                fecha="Thu, 01 Oct 2026 09:00:00 GMT",
                fuente_id="bvc_hechos_relevantes",
                certeza="confirmado",
            )
        ],
        temp_db,
    )
    despues = {s["senal_key"]: s for s in analizar(temp_db, CFG, ahora=AHORA)}

    assert set(despues) == set(antes), "la nota nueva no debe crear una señal distinta"
    clave = next(k for k, s in despues.items() if s["n_notas"] > antes[k]["n_notas"])
    assert despues[clave]["ultima"] == "2026-10-01T09:00:00Z"
    assert despues[clave]["primera"] == antes[clave]["primera"]


# ---------------------------------------------------------------- certeza
def test_certeza_viene_de_sources_yaml_no_del_id(temp_db):
    # Solo prensa -> probable
    guardar(_items_ecopetrol(), temp_db)
    solo_prensa = analizar(temp_db, CFG, ahora=AHORA)
    assert {s["certeza"] for s in solo_prensa} == {"probable"}

    # Una nota de la BVC (certeza declarada 'confirmado') -> la señal queda confirmada
    guardar(
        [
            Item(
                titulo="Ecopetrol informa adquisición de participación (hecho relevante)",
                url="https://www.bvc.com.co/hechos/ecopetrol-1",
                fecha="2026-09-30",
                fuente_id="bvc_hechos_relevantes",
                certeza="probable",  # aunque venga mal guardada, manda sources.yaml
            )
        ],
        temp_db,
    )
    con_bvc = analizar(temp_db, CFG, ahora=AHORA)
    assert any(s["certeza"] == "confirmado" for s in con_bvc)


# ---------------------------------------------------------------- exportación
def test_exportar_senales_formato_y_sin_resumen_por_defecto(temp_db):
    guardar(_items_ecopetrol(), temp_db)
    analizar(temp_db, CFG, ahora=AHORA)

    datos = construir_senales(temp_db, CFG)
    assert datos["total"] == len(datos["senales"]) >= 1
    assert datos["exportado_el"].endswith("Z")
    s = datos["senales"][0]
    for campo in ("id", "tipo", "score", "scoreBreakdown", "etiqueta", "certeza", "n_fuentes",
                  "mediosIndependientes", "articulos", "primera", "ultima", "n_notas"):
        assert campo in s
    assert s["tipo"] == "Integración"
    assert s["certeza"] == "Probable"
    assert set(s["mediosIndependientes"]) == {"La República", "Valora Analitik"}
    assert s["n_fuentes"] == 2 and s["n_notas"] == 2
    assert s["primera"] == "2026-09-29T18:40:00Z" and s["ultima"] == "2026-09-30T11:30:00Z"

    art = s["articulos"][0]
    assert set(art) == {"url", "titulo", "medio", "fecha", "certeza"}, "sin resumen por defecto"
    assert "Texto del medio" not in json.dumps(datos, ensure_ascii=False)

    cfg_con_resumen = dict(CFG, publicacion={"incluir_resumen": True})
    con = construir_senales(temp_db, cfg_con_resumen)
    assert any("resumen" in a for a in con["senales"][0]["articulos"])


def test_exportar_usa_null_donde_no_hay_dato(temp_db):
    guardar(
        [Item(titulo="Ecopetrol anuncia adquisición sin fecha", url="https://x.co/a", fecha="", fuente_id="medio_larepublica")],
        temp_db,
    )
    analizar(temp_db, CFG, ahora=AHORA)
    s = construir_senales(temp_db, CFG)["senales"][0]
    assert s["primera"] is None and s["ultima"] is None
    assert s["articulos"][0]["fecha"] is None
    assert s["scoreBreakdown"]["fechaDesconocida"] is True
    assert s["evolucion"] == [] and s["vinculosEmpresas"] == []


def test_macro_separa_eventos_y_series(temp_db):
    temp_db.guardar_serie_valor("trm", "2026-09-30", 4180.5)
    guardar(
        [Item(titulo="Señal Macro: Dólar TRM sube +2.17% situándose en 4250 COP", url="https://datos.gov.co/x#p1",
              fecha="2026-09-30", fuente_id="bvc_hechos_relevantes", certeza="confirmado")],
        temp_db,
    )
    analizar(temp_db, CFG, ahora=AHORA)
    assert construir_senales(temp_db, CFG)["total"] == 0
    macro = construir_macro(temp_db, CFG)
    assert macro["series"]["trm"][0]["valor"] == 4180.5
    assert len(macro["macro"]) == 1 and macro["macro"][0]["tipo"] == "Macro"


def test_exportar_escribe_cuatro_archivos_validos(temp_db):
    carpeta = os.path.join(temp_db.temp_dir, "data")
    rutas = exportar(temp_db, CFG, carpeta, ahora=datetime(2026, 10, 1, 17, 30, tzinfo=timezone.utc))
    assert set(rutas) == {"senales.json", "macro.json", "salud.json", "meta.json"}
    for ruta in rutas.values():
        with open(ruta, encoding="utf-8") as f:
            assert json.load(f)["exportado_el"] == "2026-10-01T17:30:00Z"
    with open(rutas["meta.json"], encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["conteos"]["senales"] == 0 and meta["esquema_version"] == 1


# ---------------------------------------------------------------- bloqueos y modo estricto
def test_fuente_bloqueada_con_403_se_ve_como_error(temp_db):
    cfg = {"fuentes": [{"id": "gnews_x", "nombre": "GN", "tipo": "gnews", "activo": True, "certeza": "probable",
                        "url": "https://mock.local/feed"}]}
    fetcher = Fetcher(db=temp_db)
    fetcher.registrar_mock("https://mock.local/feed", status_code=403, body=b"Forbidden")

    stats = {}
    recolectar(cfg, fetcher, temp_db, estadisticas=stats)

    assert stats["fuentes_error"] == 1 and stats["fuentes_ok"] == 0
    salud = construir_salud(temp_db, cfg)
    f = salud["fuentes"][0]
    assert f["estado"] == "error" and "403" in f["motivo"]
    assert salud["errores_count"] == 1


def test_fuente_vacia_pero_con_200_no_es_bloqueo(temp_db):
    cfg = {"fuentes": [{"id": "gnews_x", "tipo": "gnews", "activo": True, "url": "https://mock.local/vacio"}]}
    fetcher = Fetcher(db=temp_db)
    fetcher.registrar_mock("https://mock.local/vacio", status_code=200,
                           body=b'<?xml version="1.0"?><rss><channel></channel></rss>')
    stats = {}
    recolectar(cfg, fetcher, temp_db, estadisticas=stats)
    assert stats["fuentes_ok"] == 1 and stats["items"] == 0


def test_modo_estricto():
    assert evaluar_estricto({"fuentes_activas": 0}) is not None
    assert "ningún item" in evaluar_estricto({"fuentes_activas": 4, "fuentes_ok": 4, "items": 0})
    assert "Solo 1 de 4" in evaluar_estricto({"fuentes_activas": 4, "fuentes_ok": 1, "items": 10})
    assert evaluar_estricto({"fuentes_activas": 4, "fuentes_ok": 3, "items": 10}) is None


# ---------------------------------------------------------------- base pública
def test_base_publica_no_lleva_texto_de_medios(temp_db):
    guardar(_items_ecopetrol(), temp_db)
    temp_db.actualizar_extracto_articulo(1, "Primer párrafo copiado del artículo")
    temp_db.guardar_http_cache("https://x.co", None, None, b"<html>pagina entera</html>", 200)

    destino = os.path.join(temp_db.temp_dir, "pub", "radar_publico.db")
    res = exportar_base_publica(temp_db.db_path, destino)
    assert res["cache_http_borrado"] == 1

    con = sqlite3.connect(destino)
    assert con.execute("SELECT COUNT(*) FROM articulos").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM articulos WHERE resumen IS NOT NULL OR extracto IS NOT NULL").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM articulos WHERE titulo LIKE 'Ecopetrol%'").fetchone()[0] >= 1
    con.close()
    # El original no se toca
    assert temp_db.obtener_articulos(limit=10)[0]["resumen"] or temp_db.obtener_articulos(limit=10)[1]["resumen"]


# ---------------------------------------------------------------- Flask
def test_api_local_usa_el_mismo_formato(temp_db):
    from radar import server

    original = server.db
    server.db = temp_db
    try:
        guardar(_items_ecopetrol(), temp_db)
        analizar(temp_db, CFG, ahora=AHORA)
        cliente = server.app.test_client()
        senales = cliente.get("/api/senales").get_json()
        assert set(senales) == {"exportado_el", "total", "senales"}
        assert "series" in cliente.get("/api/macro").get_json()
        assert "fuentes" in cliente.get("/api/salud").get_json()
    finally:
        server.db = original
