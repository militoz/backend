"""
Colector HTML configurable mediante selectores CSS o patrones regex.
"""
from typing import List
import urllib.parse
from datetime import datetime
from .base import Collector, Item, limpiar_html

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


class HtmlCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "")
        self.item_selector = config.get("item_selector", "article")
        self.title_selector = config.get("title_selector", "h2, h3, a")
        self.link_selector = config.get("link_selector", "a")
        self.date_selector = config.get("date_selector", "time, .date")
        self.summary_selector = config.get("summary_selector", "p, .summary")
        self.empresa_selector = config.get("empresa_selector")

    def recolectar(self, fetcher) -> List[Item]:
        if not self.url:
            return []

        status, body, _ = fetcher.get(self.url, min_delay=self.min_delay)
        if status != 200 or not body:
            return []

        texto_html = body.decode("utf-8", errors="replace")
        items: List[Item] = []

        if BeautifulSoup is not None:
            soup = BeautifulSoup(texto_html, "html.parser")
            contenedores = soup.select(self.item_selector) if self.item_selector else [soup]

            for cont in contenedores:
                # Titulo
                t_elem = cont.select_one(self.title_selector) if self.title_selector else None
                titulo = t_elem.get_text(strip=True) if t_elem else ""

                # Enlace
                l_elem = cont.select_one(self.link_selector) if self.link_selector else None
                link = ""
                if l_elem:
                    raw_href = l_elem.get("href", "")
                    link = urllib.parse.urljoin(self.url, raw_href)

                # Fecha
                d_elem = cont.select_one(self.date_selector) if self.date_selector else None
                fecha = d_elem.get_text(strip=True) if d_elem else ""

                # Resumen
                s_elem = cont.select_one(self.summary_selector) if self.summary_selector else None
                resumen = s_elem.get_text(strip=True) if s_elem else None

                # Empresa hint
                emp_elem = cont.select_one(self.empresa_selector) if self.empresa_selector else None
                emp_hint = emp_elem.get_text(strip=True) if emp_elem else None

                if titulo and link:
                    items.append(
                        Item(
                            titulo=titulo,
                            url=link,
                            fecha=fecha,
                            resumen=resumen,
                            fuente_id=self.fuente_id,
                            certeza=self.config.get("certeza", "probable"),
                            medio=self.config.get("medio"),
                            empresa_hint=emp_hint,
                        )
                    )

        return items
