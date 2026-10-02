"""
Pipeline central de Colombia Radar: recolectar, guardar, analizar, limpiar y vencida.
Punto 0: Conserva toda la historia. limpiar() solo borra datos demo (fuente_id='demo'),
         y guardar() no descarta noticias antiguas.
Punto 2: Paso opcional 'enriquecer' para señales ambiguas, descargando los primeros ~1500 caracteres
         en la columna 'extracto' respetando robots.txt y topes por ciclo.
"""
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timedelta
import re
import html
 
from .collectors import construir, Item
from .analysis.entidades import EntidadesDetector
from .analysis.eventos import EventosDetector
from .analysis.calor import calcular_score_calor, desglosar_score
from .analysis.fuentes import mapa_fuentes, certeza_de_articulo, certeza_mayor, resolver_medio
from .util import normalizar_fecha, semana_iso, slug, hash_corto
 
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
 
logger = logging.getLogger("radar.pipeline")
 
 
def _motivo_fallo_http(fetcher, colector, f_cfg) -> str:
    """
    Si la fuente devolvió 0 items, mira cómo respondió el sitio. Una respuesta 403/429/5xx o
    la ausencia de respuesta NO es "sin novedades": es una falla y debe verse como tal.
    """
    url = getattr(colector, "url", None) or f_cfg.get("url")
    estado = getattr(fetcher, "ultimo_estado", {}).get(url) if url else None
    if not estado:
        return ""
    status, motivo = estado
    if status is None:
        return motivo or "sin respuesta del servidor"
    if status in (401, 403, 429, 451):
        return (
            f"HTTP {status}: el sitio rechazó la petición (posible bloqueo a los servidores de GitHub). "
            "Recolectar esta fuente desde un computador propio."
        )
    if status == 404:
        return "HTTP 404: la dirección ya no existe; revisar la URL en sources.yaml"
    if status >= 500:
        return f"HTTP {status}: error del servidor de la fuente"
    return ""
 
 
def recolectar(cfg: Dict[str, Any], fetcher, db, estadisticas: Optional[Dict[str, Any]] = None) -> List[Item]:
    """
    Ejecuta la recolección sobre todas las fuentes habilitadas en la configuración.
    Garantiza que una fuente caída nunca tumbe a las demás (Regla 4).
    Registra estadísticas de salud en la tabla fuente_salud.
    Si se pasa un dict en 'estadisticas', se llena con el resumen de la corrida
    (fuentes_activas, fuentes_ok, fuentes_error, items, detalle por fuente).
    """
    fuentes = cfg.get("fuentes", [])
    todos_items: List[Item] = []
    stats = estadisticas if estadisticas is not None else {}
    stats.update({"fuentes_activas": 0, "fuentes_ok": 0, "fuentes_error": 0, "items": 0, "detalle": {}})
 
    for f_cfg in fuentes:
        fuente_id = f_cfg.get("id")
        if not fuente_id:
            continue
 
        # Verificar si está habilitada (por defecto True salvo que diga activo: false)
        if not f_cfg.get("activo", True):
            continue
 
        colector = construir(f_cfg)
        if not colector:
            logger.warning(f"No se pudo construir colector para fuente: {fuente_id}")
            continue
 
        stats["fuentes_activas"] += 1
        items_fuente: List[Item] = []
        exito = False
        motivo_error = ""
 
        try:
            items_fuente = colector.recolectar(fetcher)
            exito = True
            if not items_fuente:
                motivo_http = _motivo_fallo_http(fetcher, colector, f_cfg)
                if motivo_http:
                    exito = False
                    motivo_error = motivo_http
                    logger.error(f"Fuente '{fuente_id}' sin datos: {motivo_http}")
            if exito:
                todos_items.extend(items_fuente)
                logger.info(f"Fuente '{fuente_id}' recolectó {len(items_fuente)} items.")
        except Exception as e:
            exito = False
            motivo_error = str(e)
            logger.error(f"Fallo en recolección de fuente '{fuente_id}': {e}", exc_info=True)
 
        if exito:
            stats["fuentes_ok"] += 1
            stats["items"] += len(items_fuente)
        else:
            stats["fuentes_error"] += 1
        stats["detalle"][fuente_id] = {"ok": exito, "items": len(items_fuente) if exito else 0, "motivo": motivo_error}
 
        # Registrar salud de la fuente en la base de datos
        db.registrar_salud(
            fuente_id=fuente_id,
            items_recolectados=len(items_fuente) if exito else 0,
            exito=exito,
            motivo_error=motivo_error,
            max_corridas_vacias=cfg.get("salud", {}).get("max_corridas_vacias", 3),
            umbral_caida_brusca=cfg.get("salud", {}).get("umbral_caida_brusca", 0.5),
        )
 
    return todos_items
 
 
def evaluar_estricto(stats: Dict[str, Any], minimo: float = 0.5) -> Optional[str]:
    """
    Modo estricto: devuelve el motivo de falla (texto) si la corrida debe considerarse fallida,
    o None si está bien. Evita ejecuciones "verdes" que en realidad no recolectaron nada.
    """
    activas = stats.get("fuentes_activas", 0)
    if activas == 0:
        return "No hay fuentes activas en config/sources.yaml."
    if stats.get("items", 0) == 0:
        return "No se recolectó ningún item en ninguna fuente."
    if stats.get("fuentes_ok", 0) / activas < minimo:
        return f"Solo {stats.get('fuentes_ok', 0)} de {activas} fuentes respondieron (mínimo exigido: {minimo:.0%})."
    return None
 
 
def guardar(items: List[Item], db) -> int:
    """
    Guarda los items recolectados en la tabla 'articulos'.
    Punto 0 (HISTORIA): Conserva toda la historia; NO descarta por fechas anteriores al 1 de enero.
    Retorna el número de artículos procesados exitosamente.
    """
    guardados = 0
    for it in items:
        # Guardado en base de datos sin descarte histórico
        res = db.guardar_articulo(
            url=it.url,
            titulo=it.titulo,
            fuente_id=it.fuente_id,
            fecha=it.fecha,
            resumen=it.resumen,
            extracto=it.extracto,
            medio=it.medio,
            certeza=it.certeza,
        )
        if res:
            guardados += 1
    return guardados
 
 
def enriquecer_articulo(url: str, fetcher, max_caracteres: int = 1500) -> Optional[str]:
    """
    Punto 2: Descarga respetuosa del arranque del artículo (~1500 caracteres),
    respetando robots.txt, sin saltar paywalls. Extrae texto limpio de los primeros párrafos.
    """
    if not fetcher:
        return None
 
    status, body, _ = fetcher.get(url, use_cache=True)
    if status != 200 or not body:
        return None
 
    texto_html = body.decode("utf-8", errors="replace")
 
    if BeautifulSoup is not None:
        soup = BeautifulSoup(texto_html, "html.parser")
        # Remover scripts, estilos, nav, footer
        for elemento in soup(["script", "style", "nav", "footer", "header", "aside"]):
            elemento.decompose()
 
        parrafos = soup.find_all("p")
        textos = []
        acumulado = 0
        for p in parrafos:
            txt = p.get_text(strip=True)
            if len(txt) > 30:  # Evitar avisos breves de cookies o autor
                textos.append(txt)
                acumulado += len(txt)
                if acumulado >= max_caracteres:
                    break
 
        texto_plano = " ".join(textos)
    else:
        # Fallback sin BeautifulSoup
        texto_plano = re.sub(r"<[^>]+>", " ", texto_html)
        texto_plano = html.unescape(texto_plano)
        texto_plano = " ".join(texto_plano.split())
 
    return texto_plano[:max_caracteres] if texto_plano else None
 
 
def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
 
 
def _elegir_senal_existente(existentes: List[Dict[str, Any]], primera_nueva: Optional[str], dias: int = 21):
    """
    Un mismo tema conserva su ID mientras siga activo: se reutiliza la señal existente
    si su última nota está a menos de 'dias' días de la primera nota nueva.
    """
    if not existentes:
        return None
    if not primera_nueva:
        return existentes[0]
    limite = datetime.strptime(primera_nueva[:19], "%Y-%m-%dT%H:%M:%S") - timedelta(days=dias)
    limite_iso = limite.strftime("%Y-%m-%dT%H:%M:%SZ")
    for e in existentes:  # ya vienen de la más reciente a la más antigua
        ref = e.get("ultima") or e.get("primera")
        if not ref or ref >= limite_iso:
            return e
    return None
 
 
def analizar(db, cfg: Dict[str, Any], fetcher=None, ahora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Analiza artículos no procesados o recientes:
    1. Extrae empresas (priorizando empresa_hint) e insumos.
    2. Detecta eventos según reglas en eventos.yaml.
    3. Punto 2: Si la regla es ambigua o solo_titulo es False y falta extracto, enriquece con ~1500 chars (con tope de peticiones).
    4. Agrupa en señales con ID ESTABLE (el mismo tema se actualiza, no se duplica) y calcula
       certeza (la declarada en sources.yaml), fechas reales, medios y desglose del score.
    """
    mapa = mapa_fuentes(cfg)
    max_articulos = (cfg.get("analisis") or {}).get("max_articulos", 300)
    articulos = db.obtener_articulos(limit=max_articulos, solo_no_demo=True)
    ent_detector = EntidadesDetector()
    ev_detector = EventosDetector()
 
    config_enriquecer = cfg.get("enriquecer", {})
    enriquecer_activo = config_enriquecer.get("activo", False)
    max_peticiones_enriquecer = config_enriquecer.get("max_peticiones_por_ciclo", 10)
    peticiones_hechas = 0
 
    senales_generadas: List[Dict[str, Any]] = []
    clusters: Dict[str, Dict[str, Any]] = {}
 
    for art in articulos:
        titulo = art.get("titulo") or ""
        url = art.get("url") or ""
        extracto = art.get("extracto")
        resumen = art.get("resumen") or ""
        art_id = art.get("id")
 
        # Evaluar coincidencia preliminar con título
        coincidencias = ev_detector.evaluar_texto(titulo)
 
        # Punto 2: Si hay coincidencia ambigua y enriquecer está activo, descargar extracto
        hay_ambigua = any(c.get("es_ambigua") for c in coincidencias)
        if enriquecer_activo and fetcher and (hay_ambigua or not coincidencias) and not extracto:
            if peticiones_hechas < max_peticiones_enriquecer:
                nuevo_extracto = enriquecer_articulo(url, fetcher)
                if nuevo_extracto:
                    db.actualizar_extracto_articulo(art_id, nuevo_extracto)
                    extracto = nuevo_extracto
                    peticiones_hechas += 1
                    # Reevaluar con extracto disponible
                    coincidencias = ev_detector.evaluar_texto(titulo, texto_ampliado=extracto)
 
        if not coincidencias:
            continue
 
        # Una nota genera UNA señal: la regla de mayor peso (evita duplicados tipo
        # "Licencia" + "Regulación sectorial" por el mismo titular).
        coincidencias = sorted(coincidencias, key=lambda m: m["peso_tipo"], reverse=True)[:1]
 
        # Detectar empresas e insumos en el texto
        texto_busqueda = f"{titulo} {extracto or resumen}"
        empresas, sectores = ent_detector.detectar_empresas(texto_busqueda)
        insumos = ent_detector.detectar_insumos(texto_busqueda)
 
        for match_ev in coincidencias:
            tipo = match_ev["tipo"]
            etiqueta = match_ev["etiqueta"]
            # Con empresa: se agrupa por la empresa mencionada primero (el sujeto del titular).
            # Sin empresa: una señal por artículo; antes todas las notas del mismo tipo caían en un
            # solo grupo "sin_empresa" y se mezclaban noticias no relacionadas entre sí.
            emp_clave = empresas[0] if empresas else f"sin_empresa-{hash_corto(url or titulo, 6)}"
            cluster_key = f"{tipo}|{emp_clave}|{etiqueta}"
 
            c = clusters.get(cluster_key)
            if c is None:
                c = clusters[cluster_key] = {
                    "tipo": tipo,
                    "emp_clave": emp_clave,
                    "etiqueta_regla": etiqueta,
                    "etiqueta": f"{etiqueta}: {titulo}" if len(titulo) < 70 else etiqueta,
                    "insumo": None,
                    "peso_tipo": match_ev["peso_tipo"],
                    "razonamiento": match_ev["razonamiento"],
                    "empresas": set(),
                    "sectores": set(),
                    "ids": [],
                }
            c["empresas"].update(empresas)
            c["sectores"].update(sectores)
            if art_id is not None and art_id not in c["ids"]:
                c["ids"].append(art_id)
            if insumos and not c["insumo"]:
                c["insumo"] = insumos[0]
 
    # Convertir clusters en señales con clave estable y guardarlas (upsert)
    for c in clusters.values():
        base = f"{c['tipo']}|{c['emp_clave']}|{c['etiqueta_regla']}"
        h = hash_corto(base)
        prefijo = f"{slug(c['tipo'])}_{slug(c['emp_clave'])}_"
 
        # ¿Es el mismo tema de una corrida anterior?
        patron = _escapar_like(prefijo) + "%" + _escapar_like(f"_{h}")
        existentes = db.buscar_senales_por_patron(patron)
 
        arts_nuevas = db.obtener_articulos_por_ids(c["ids"])
        fechas_nuevas = [f for f in (normalizar_fecha(a.get("fecha")) for a in arts_nuevas) if f]
        primera_nueva = min(fechas_nuevas) if fechas_nuevas else None
        previa = _elegir_senal_existente(existentes, primera_nueva)
 
        ids = set(c["ids"])
        empresas_f = set(c["empresas"])
        sectores_f = set(c["sectores"])
        etiqueta_f = c["etiqueta"]
        insumo_f = c["insumo"]
        if previa:
            senal_key = previa["senal_key"]
            ids |= set(previa.get("articulos_ids") or [])
            empresas_f |= set(previa.get("empresas") or [])
            sectores_f |= set(previa.get("sectores") or [])
            etiqueta_f = previa.get("etiqueta") or etiqueta_f
            insumo_f = previa.get("insumo") or insumo_f
        else:
            semana = semana_iso(primera_nueva) or "sin-fecha"
            senal_key = f"{prefijo}{semana}_{h}"
 
        # Métricas calculadas sobre TODAS las notas del tema (no solo las de esta corrida)
        arts = db.obtener_articulos_por_ids(sorted(ids))
        fechas = [f for f in (normalizar_fecha(a.get("fecha")) for a in arts) if f]
        primera = min(fechas) if fechas else None
        ultima = max(fechas) if fechas else None
 
        medios: List[str] = []
        vistos = set()
        for a in arts:
            m = resolver_medio(a, mapa)
            if m and slug(m) not in vistos:
                vistos.add(slug(m))
                medios.append(m)
        n_fuentes = len(medios) or len({a.get("fuente_id") for a in arts if a.get("fuente_id")}) or 1
 
        certeza = certeza_mayor(certeza_de_articulo(a, mapa) for a in arts)
        desglose = desglosar_score(c["peso_tipo"], certeza, n_fuentes, ultima, ahora=ahora)
        score = desglose.pop("score")
        desglose["mediosCount"] = len(medios)
        desglose["articulosCount"] = len(arts)
 
        senal_dict = {
            "senal_key": senal_key,
            "cluster_id": int(hash_corto(senal_key, 8), 16) % 1_000_000_000,
            "tipo": c["tipo"],
            "etiqueta": etiqueta_f,
            "insumo": insumo_f,
            "certeza": certeza,
            "score": score,
            "score_breakdown": desglose,
            "razonamiento": c["razonamiento"],
            "empresas": sorted(empresas_f),
            "sectores": sorted(sectores_f),
            "articulos_ids": sorted(ids),
            "medios": medios,
            "n_fuentes": n_fuentes,
            "n_notas": len(arts),
            "primera": primera,
            "ultima": ultima,
        }
        db.guardar_senal(senal_dict)
        senales_generadas.append(senal_dict)
 
    # Limpieza: señales de reglas o detectores anteriores que ya no se reproducen con los mismos artículos.
    obsoletas = db.eliminar_senales_obsoletas(
        {a.get("id") for a in articulos if a.get("id") is not None},
        {s["senal_key"] for s in senales_generadas},
    )
    if obsoletas:
        logger.info(f"Señales obsoletas eliminadas: {obsoletas}")
 
    return senales_generadas
 
 
def noticias_por_empresa(db, cfg: Dict[str, Any], max_por_empresa: int = 15) -> Dict[str, Any]:
    """
    Índice de TODAS las noticias que mencionan a cada empresa del catálogo, genere o no una señal.
    Alimenta la ficha por empresa. Solo expone titular, medio, fecha y enlace (sin copiar texto).
    Incluye también las empresas sin noticias (n_noticias = 0) para poder mostrar "sin noticias".
    """
    mapa = mapa_fuentes(cfg)
    limite = (cfg.get("analisis") or {}).get("max_articulos_indice", 2000)
    articulos = db.obtener_articulos(limit=limite, solo_no_demo=True)
    det = EntidadesDetector()
 
    por_empresa: Dict[str, List[Dict[str, Any]]] = {}
    con_empresa = 0
    for art in articulos:
        texto = f"{art.get('titulo') or ''} {art.get('extracto') or art.get('resumen') or ''}"
        empresas, _ = det.detectar_empresas(texto)
        if not empresas:
            continue
        con_empresa += 1
        item = {
            "titulo": art.get("titulo") or "",
            "url": art.get("url") or "",
            "medio": resolver_medio(art, mapa),
            "fecha": normalizar_fecha(art.get("fecha")),
        }
        for i, nombre in enumerate(empresas):
            por_empresa.setdefault(nombre, []).append({**item, "principal": i == 0})
 
    total = len(articulos)
    salida = []
    for emp in det.empresas:
        nombre = emp.get("nombre", "")
        notas = sorted(por_empresa.get(nombre, []), key=lambda n: n.get("fecha") or "", reverse=True)
        salida.append({
            "nombre": nombre,
            "ticker": emp.get("ticker"),
            "ticker_preferencial": emp.get("ticker_preferencial"),
            "sector": emp.get("sector"),
            "n_noticias": len(notas),
            "ultima": notas[0]["fecha"] if notas else None,
            "noticias": notas[:max_por_empresa],
        })
    salida.sort(key=lambda e: (-e["n_noticias"], e["nombre"]))
 
    logger.info(f"Índice por empresa: {total} artículos, {con_empresa} mencionan alguna empresa del catálogo.")
    return {
        "exportado_el": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "estadisticas": {"articulos_analizados": total, "con_empresa": con_empresa, "sin_empresa": total - con_empresa},
        "empresas": salida,
    }
 
 
def limpiar(db) -> int:
    """
    Punto 0 (HISTORIA):
    limpiar() hoy ÚNICAMENTE borra los datos demo (fuente_id='demo').
    Conserva la historia completa de noticias y series reales.
    """
    borrados = db.limpiar_demo()
    logger.info(f"Limpieza ejecutada: {borrados} artículos demo eliminados. Historia real conservada.")
    return borrados
 
 
def vencida(senal: Dict[str, Any], dias: int = 30) -> bool:
    """Retorna si una señal ha superado la ventana de vigencia para el tablero."""
    creado_en = senal.get("creado_en")
    if not creado_en:
        return False
    try:
        dt = datetime.fromisoformat(creado_en)
        return (datetime.utcnow() - dt).days > dias
    except Exception:
        return False
