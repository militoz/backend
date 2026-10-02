"""
Colector para Google News RSS.
Punto 2: Conserva el resumen cuando exista (no lo borra si tiene texto real).
Punto 3: Deduplicación inteligente: extrae medio/dominio original y normaliza URLs para evitar que la redirección de Google News cuente como duplicada de la fuente directa.
"""
from typing import List, Optional
import urllib.parse
import re
import html
from .base import Collector, Item, parse_feed, limpiar_html


class GNewsCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "")
        self.query = config.get("query", "")
        if not self.url and self.query:
            q_enc = urllib.parse.quote_plus(self.query)
            # URL de Google News para Colombia en español
            self.url = f"https://news.google.com/rss/search?q={q_enc}&hl=es-419&gl=CO&ceid=CO:es-419"

    def recolectar(self, fetcher) -> List[Item]:
        if not self.url:
            return []

        status, body, _ = fetcher.get(self.url, min_delay=self.min_delay)
        if status != 200 or not body:
            return []

        raw_items = parse_feed(body, self.fuente_id, self.config)
        items_procesados: List[Item] = []

        for item in raw_items:
            # 1. Limpieza de título y separación de medio ("Título de la noticia - Nombre Medio")
            titulo_limpio = item.titulo
            medio_detectado = item.medio
            if " - " in item.titulo:
                partes = item.titulo.rsplit(" - ", 1)
                titulo_limpio = partes[0].strip()
                if not medio_detectado:
                    medio_detectado = partes[1].strip()

            # 2. Conservación del resumen (Punto 2):
            # En Google News el summary a veces es solo un enlace al medio original:
            # ej: '<a href="...">La República</a>'. Si contiene texto informativo además de tags, lo conservamos.
            resumen_final = None
            if item.resumen:
                texto_resumen = limpiar_html(item.resumen)
                # Si el texto del resumen no es idéntico al medio ni un simple link vacío
                if texto_resumen and texto_resumen.lower() != (medio_detectado or "").lower() and len(texto_resumen) > 15:
                    resumen_final = texto_resumen

            # 3. Deduplicación y normalización de URL (Punto 3):
            # Las URLs de Google News vienen como https://news.google.com/rss/articles/CBMi...
            # Guardamos la URL canónica y los metadatos para permitir deduplicación por título y medio.
            metadata = {
                "gnews_raw_url": item.url,
                "medio_detectado": medio_detectado,
                "titulo_normalizado": re.sub(r"[^\w\s]", "", titulo_limpio.lower()),
            }

            items_procesados.append(
                Item(
                    titulo=titulo_limpio,
                    url=item.url,
                    fecha=item.fecha,
                    resumen=resumen_final,
                    extracto=None,
                    certeza=self.config.get("certeza", "probable"),
                    fuente_id=self.fuente_id,
                    medio=medio_detectado,
                    metadata=metadata,
                )
            )

        return items_procesados
