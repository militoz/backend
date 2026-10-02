"""
Colector para mapas de sitio XML (Sitemaps).
"""
from typing import List
import xml.etree.ElementTree as ET
import re
from datetime import datetime
from .base import Collector, Item


class SitemapCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "")
        self.filter_regex = config.get("filter_regex", "")

    def recolectar(self, fetcher) -> List[Item]:
        if not self.url:
            return []

        status, body, _ = fetcher.get(self.url, min_delay=self.min_delay)
        if status != 200 or not body:
            return []

        items: List[Item] = []
        try:
            root = ET.fromstring(body)
        except Exception:
            return items

        # Namespaces comunes de sitemaps
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9", "news": "http://www.google.com/schemas/sitemap-news/0.9"}

        for url_node in root.findall(".//sm:url", ns) or root.findall(".//url"):
            loc = (url_node.findtext("sm:loc", namespaces=ns) or url_node.findtext("loc") or "").strip()
            lastmod = (url_node.findtext("sm:lastmod", namespaces=ns) or url_node.findtext("lastmod") or "").strip()

            if not loc:
                continue

            if self.filter_regex and not re.search(self.filter_regex, loc, re.IGNORECASE):
                continue

            # Buscar título de noticia si es news sitemap
            news_title = (url_node.findtext(".//news:title", namespaces=ns) or "").strip()
            if not news_title:
                # Deducir título a partir del slug de la URL
                slug = loc.rstrip("/").split("/")[-1]
                slug_limpio = re.sub(r"[-_]", " ", re.sub(r"\.\w+$", "", slug))
                news_title = slug_limpio.capitalize()

            items.append(
                Item(
                    titulo=news_title,
                    url=loc,
                    fecha=lastmod,
                    fuente_id=self.fuente_id,
                    certeza=self.config.get("certeza", "probable"),
                    medio=self.config.get("medio"),
                )
            )

        return items
