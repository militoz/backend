"""
Colector para la Superintendencia de Sociedades (Supersociedades).
Extrae autos y noticias sobre procesos de reorganización, insolvencia, intervención y liquidación judicial.
Certeza asignada: 'confirmado' (fuente oficial directa, peso 1.0).
Extrae la sociedad afectada como 'empresa_hint'.
"""
from typing import List
import urllib.parse
from datetime import datetime
from .base import Collector, Item

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


class SupersociedadesCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "")
        self.item_selector = config.get("item_selector", ".proceso-item, tr, .noticia")
        self.title_selector = config.get("title_selector", ".asunto, .titulo, a")
        self.link_selector = config.get("link_selector", "a")
        self.date_selector = config.get("date_selector", ".fecha, time, td:nth-child(2)")
        self.sociedad_selector = config.get("sociedad_selector", ".sociedad, .concursada, td:nth-child(1)")

    def recolectar(self, fetcher) -> List[Item]:
        if not self.url:
            return []

        status, body, _ = fetcher.get(self.url, min_delay=self.min_delay)
        if status != 200 or not body:
            return []

        items: List[Item] = []
        texto_html = body.decode("utf-8", errors="replace")

        if BeautifulSoup is not None:
            soup = BeautifulSoup(texto_html, "html.parser")
            elementos = soup.select(self.item_selector) if self.item_selector else []

            for elem in elementos:
                l_elem = elem.select_one(self.link_selector) if self.link_selector else elem.find("a")
                if not l_elem:
                    continue

                raw_href = l_elem.get("href", "")
                link = urllib.parse.urljoin(self.url, raw_href)

                t_elem = elem.select_one(self.title_selector) if self.title_selector else l_elem
                titulo = t_elem.get_text(strip=True) if t_elem else l_elem.get_text(strip=True)

                soc_elem = elem.select_one(self.sociedad_selector) if self.sociedad_selector else None
                empresa_hint = soc_elem.get_text(strip=True) if soc_elem else None

                if empresa_hint and empresa_hint.lower() not in titulo.lower():
                    titulo_completo = f"Supersociedades [{empresa_hint}]: {titulo}"
                else:
                    titulo_completo = f"Supersociedades: {titulo}"

                d_elem = elem.select_one(self.date_selector) if self.date_selector else None
                fecha = d_elem.get_text(strip=True) if d_elem else ""

                if titulo and link:
                    items.append(
                        Item(
                            titulo=titulo_completo,
                            url=link,
                            fecha=fecha,
                            resumen=f"Proceso de insolvencia o reorganización empresarial en Supersociedades referente a {empresa_hint or 'sociedad'}.",
                            fuente_id=self.fuente_id,
                            certeza="confirmado",
                            empresa_hint=empresa_hint,
                            medio="Supersociedades (Oficial)",
                        )
                    )

        return items
