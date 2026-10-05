"""
Exportación a JSON para la interfaz. Este módulo es la ÚNICA fuente del formato:
lo usan tanto el comando `python run.py exportar` (GitHub) como el servidor Flask local.

Regla de oro: donde no hay dato, el JSON lleva null o lista vacía. Nunca un valor inventado.
Por defecto NO se publican resúmenes de artículos (son texto de los medios): solo enlace,
titular, medio, fecha y certeza. Se puede activar en sources.yaml (publicacion.incluir_resumen).
"""
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml

from .analysis.calor import PESOS_CERTEZA
from .analysis.fuentes import (
    certeza_de_articulo,
    mapa_fuentes,
    resolver_medio,
    tipo_de_fuente,
)
from .util import normalizar_fecha

ESQUEMA_VERSION = 1

TIPOS_INTERFAZ = {
    "integracion": "Integración",
    "insolvencia": "Insolvencia",
    "regulatorio": "Regulatorio",
    "suministro": "Suministro",
    "inversion": "Inversión",
    "nombramiento": "Nombramiento",
    "macro": "Macro",
}

CERTEZA_INTERFAZ = {
    "oficial": "Oficial",
    "confirmado": "Confirmada",
    "probable": "Probable",
    "rumor": "Rumor",
}

DIR_CONFIG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config"))


def _ahora_iso(ahora: Optional[datetime] = None) -> str:
    ahora = ahora or datetime.now(timezone.utc)
    return ahora.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _publicacion(cfg: Dict[str, Any]) -> Dict[str, Any]:
    pub = (cfg or {}).get("publicacion") or {}
    return {
        "incluir_resumen": bool(pub.get("incluir_resumen", False)),
        "max_senales": int(pub.get("max_senales", 200)),
        "max_puntos_serie": int(pub.get("max_puntos_serie", 30)),
    }


def _articulos_de_senal(db, senal: Dict[str, Any], mapa, incluir_resumen: bool) -> List[Dict[str, Any]]:
    arts = db.obtener_articulos_por_ids(senal.get("articulos_ids") or [])
    salida = []
    for a in arts:
        item = {
            "url": a.get("url"),
            "titulo": a.get("titulo"),
            "medio": resolver_medio(a, mapa),
            "fecha": normalizar_fecha(a.get("fecha")),
            "certeza": CERTEZA_INTERFAZ.get(certeza_de_articulo(a, mapa), "Probable"),
        }
        if incluir_resumen:
            item["resumen"] = a.get("resumen") or None
        salida.append(item)
    # Más reciente primero; las que no tienen fecha, al final
    salida.sort(key=lambda x: x["fecha"] or "", reverse=True)
    return salida


def _tipo_interfaz(tipo: Optional[str]) -> str:
    t = (tipo or "").lower()
    return TIPOS_INTERFAZ.get(t, (tipo or "").capitalize())


def construir_senales(db, cfg: Dict[str, Any], ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Contenido de senales.json (señales corporativas; las macro van en macro.json)."""
    pub = _publicacion(cfg)
    mapa = mapa_fuentes(cfg)
    filas = [s for s in db.obtener_senales_exportables(pub["max_senales"]) if (s.get("tipo") or "").lower() != "macro"]

    senales = []
    for s in filas:
        arts = _articulos_de_senal(db, s, mapa, pub["incluir_resumen"])
        senales.append(
            {
                "id": s["senal_key"],
                "cluster_id": s.get("cluster_id"),
                "tipo": _tipo_interfaz(s.get("tipo")),
                "score": s.get("score"),
                "scoreBreakdown": s.get("score_breakdown"),
                "etiqueta": s.get("etiqueta"),
                "insumo": s.get("insumo") or None,
                "certeza": CERTEZA_INTERFAZ.get((s.get("certeza") or "").lower(), "Probable"),
                "n_fuentes": s.get("n_fuentes"),
                "mediosIndependientes": s.get("medios") or [],
                "sectores": s.get("sectores") or [],
                "evolucion": [],
                "empresas": s.get("empresas") or [],
                "vinculosEmpresas": [],
                "candidatos": [],
                "razonamiento": s.get("razonamiento") or None,
                "articulos": arts,
                "primera": s.get("primera"),
                "ultima": s.get("ultima"),
                "n_notas": s.get("n_notas"),
            }
        )
    return {"exportado_el": _ahora_iso(ahora), "total": len(senales), "senales": senales}


def construir_macro(db, cfg: Dict[str, Any], ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Contenido de macro.json: series numéricas + eventos macro detectados."""
    pub = _publicacion(cfg)
    mapa = mapa_fuentes(cfg)

    series = {
        sid: db.obtener_ultimos_valores_serie(sid, limite=pub["max_puntos_serie"])
        for sid in db.obtener_series_ids()
    }

    eventos = []
    for s in db.obtener_senales_exportables(pub["max_senales"]):
        if (s.get("tipo") or "").lower() != "macro":
            continue
        eventos.append(
            {
                "id": s["senal_key"],
                "cluster_id": s.get("cluster_id"),
                "etiqueta": s.get("etiqueta"),
                "tipo": "Macro",
                "ultima": s.get("ultima"),
                "n_fuentes": s.get("n_fuentes"),
                "n_notas": s.get("n_notas"),
                "impacto": None,
                "sectoresAfectados": s.get("sectores") or [],
                "resumen": None,
                "articulos": _articulos_de_senal(db, s, mapa, pub["incluir_resumen"]),
            }
        )
    return {"exportado_el": _ahora_iso(ahora), "series": series, "macro": eventos}


def _ids_fuentes_activas(cfg: Dict[str, Any]) -> Optional[set]:
    """IDs de las fuentes encendidas en sources.yaml. None = no hay lista de fuentes: no se filtra nada."""
    fuentes = (cfg or {}).get("fuentes") or []
    if not fuentes:
        return None
    return {f.get("id") for f in fuentes if f.get("id") and f.get("activo", True)}


def construir_salud(db, cfg: Dict[str, Any], ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Contenido de salud.json: estado de cada fuente ENCENDIDA según la última corrida.

    Las fuentes apagadas (activo: false) conservan en la base su último intento, pero ese dato es
    historia: no se cuentan como errores. Sus nombres salen aparte, en "desactivadas".
    """
    mapa = mapa_fuentes(cfg)
    activas = _ids_fuentes_activas(cfg)
    fuentes = []
    desactivadas = []
    for f in db.obtener_salud_fuentes():
        if activas is not None and f["fuente_id"] not in activas:
            desactivadas.append(f["fuente_id"])
            continue
        f_cfg = mapa.get(f["fuente_id"]) or {}
        fuentes.append(
            {
                "fuente_id": f["fuente_id"],
                "nombre": f_cfg.get("nombre") or f["fuente_id"],
                "tipo": tipo_de_fuente(f_cfg) if f_cfg else None,
                "estado": f.get("estado"),
                "items_recolectados": f.get("items_recolectados"),
                "ultima_recoleccion": normalizar_fecha(f.get("ultima_recoleccion")),
                "motivo": f.get("motivo_degradada") or None,
                "exitos": f.get("exitos"),
                "fallos": f.get("fallos"),
            }
        )
    degradadas = [f for f in fuentes if f["estado"] == "degradada"]
    con_error = [f for f in fuentes if f["estado"] == "error"]
    ultimas = [f["ultima_recoleccion"] for f in fuentes if f["ultima_recoleccion"]]
    return {
        "exportado_el": _ahora_iso(ahora),
        "ultima_recoleccion": max(ultimas) if ultimas else None,
        "total_fuentes": len(fuentes),
        "degradadas_count": len(degradadas),
        "errores_count": len(con_error),
        "desactivadas": desactivadas,
        "fuentes": fuentes,
        "degradadas": degradadas,
    }


def construir_noticias_por_empresa(db, cfg: Dict[str, Any], ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Contenido de noticias_por_empresa.json: noticias por emisor (incluye los que tienen 0) y cobertura."""
    # Import local para evitar un import circular (pipeline ya importa utilidades de este paquete).
    from .pipeline import noticias_por_empresa

    datos = noticias_por_empresa(db, cfg)
    datos["exportado_el"] = _ahora_iso(ahora)
    return datos


def _leer_yaml(nombre: str) -> Dict[str, Any]:
    ruta = os.path.join(DIR_CONFIG, nombre)
    if not os.path.exists(ruta):
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def construir_meta(db, cfg: Dict[str, Any], ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Contenido de meta.json: hora real de generación, conteos y los pesos que usa el backend."""
    reglas = _leer_yaml("eventos.yaml").get("eventos", [])
    pesos_tipo: Dict[str, float] = {}
    for r in reglas:
        nombre = _tipo_interfaz(r.get("tipo"))
        pesos_tipo[nombre] = max(pesos_tipo.get(nombre, 0.0), float(r.get("peso", 1.0)))
    sectores = sorted({e.get("sector") for e in _leer_yaml("empresas.yaml").get("empresas", []) if e.get("sector")})

    pub = _publicacion(cfg)
    senales = construir_senales(db, cfg, ahora)
    macro = construir_macro(db, cfg, ahora)
    return {
        "exportado_el": _ahora_iso(ahora),
        "esquema_version": ESQUEMA_VERSION,
        "generado_por": "colombia_radar",
        "incluye_resumenes": pub["incluir_resumen"],
        "conteos": {
            "senales": senales["total"],
            "eventos_macro": len(macro["macro"]),
            "series": len(macro["series"]),
            "articulos": db.contar_articulos(),
            "fuentes": construir_salud(db, cfg, ahora)["total_fuentes"],
        },
        "sectores": sectores,
        "pesosTipo": pesos_tipo,
        "pesosCerteza": {CERTEZA_INTERFAZ[k]: v for k, v in PESOS_CERTEZA.items() if k in CERTEZA_INTERFAZ},
    }


def _escribir_json(ruta: str, datos: Dict[str, Any]):
    """Escritura atómica: nunca queda un JSON a medias."""
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, ruta)


def exportar(db, cfg: Dict[str, Any], salida: str, ahora: Optional[datetime] = None) -> Dict[str, str]:
    """Escribe senales.json, macro.json, salud.json, meta.json y noticias_por_empresa.json en la carpeta 'salida'."""
    os.makedirs(salida, exist_ok=True)
    ahora = ahora or datetime.now(timezone.utc)
    paquetes = {
        "senales.json": construir_senales(db, cfg, ahora),
        "macro.json": construir_macro(db, cfg, ahora),
        "salud.json": construir_salud(db, cfg, ahora),
        "meta.json": construir_meta(db, cfg, ahora),
        "noticias_por_empresa.json": construir_noticias_por_empresa(db, cfg, ahora),
    }
    rutas = {}
    for nombre, datos in paquetes.items():
        ruta = os.path.join(salida, nombre)
        _escribir_json(ruta, datos)
        rutas[nombre] = ruta
    return rutas


def exportar_base_publica(ruta_origen: str, ruta_destino: str) -> Dict[str, int]:
    """
    Copia la base para publicarla en la rama pública SIN texto de medios:
    se borran los extractos y resúmenes de los artículos y todo el caché HTTP.
    Se conservan titulares, enlaces, fechas, señales, series y salud de fuentes.
    """
    os.makedirs(os.path.dirname(os.path.abspath(ruta_destino)), exist_ok=True)
    if os.path.exists(ruta_destino):
        os.remove(ruta_destino)

    origen = sqlite3.connect(ruta_origen)
    destino = sqlite3.connect(ruta_destino)
    try:
        origen.backup(destino)
    finally:
        origen.close()

    try:
        cur = destino.cursor()
        cur.execute("UPDATE articulos SET extracto = NULL, resumen = NULL")
        limpiados = cur.rowcount
        cur.execute("DELETE FROM http_cache")
        cache = cur.rowcount
        destino.commit()
        destino.execute("VACUUM")
    finally:
        destino.close()
    return {"articulos_sin_texto": limpiados, "cache_http_borrado": cache}
