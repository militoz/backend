"""
Colector para la Superintendencia de Industria y Comercio (SIC).
Extrae trámites y resoluciones de Integraciones Empresariales (fusiones, adquisiciones).
Certeza asignada: 'confirmado' (fuente oficial directa, peso 1.0).
Extrae empresas intervinientes como 'empresa_hint'.
"""
from typing import List
import urllib.parse
from datetime import datetime
from .base import Collector, Item

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


class SicCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "")
        self.item_selector = config.get("item_selector", ".integracion-item, tr, .noticia")
        self.title_selector = config.get("title_selector", ".asunto, .titulo, a")
        self.link_selector = config.get("link_selector", "a")
        self.date_selector = config.get("date_selector", ".fecha, time, td:nth-child(2)")
        self.intervinientes_selector = config.get("intervinientes_selector", ".intervinientes, .empresas, td:nth-child(1)")

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

                inter_elem = elem.select_one(self.intervinientes_selector) if self.intervinientes_selector else None
                empresa_hint = inter_elem.get_text(strip=True) if inter_elem else None

                # Si no trae palabra integración en el título, prefijarlo
                if "integraci" not in titulo.lower():
                    titulo_completo = f"SIC Integración Empresarial: {titulo}"
                else:
                    titulo_completo = f"SIC: {titulo}"

                d_elem = elem.select_one(self.date_selector) if self.date_selector else None
                fecha = d_elem.get_text(strip=True) if d_elem else ""

                if titulo and link:
                    items.append(
                        Item(
                            titulo=titulo_completo,
                            url=link,
                            fecha=fecha,
                            resumen=f"Trámite o resolución de integración empresarial ante la SIC con partes: {empresa_hint or 'empresas solicitantes'}.",
                            fuente_id=self.fuente_id,
                            certeza="confirmado",
                            empresa_hint=empresa_hint,
                            medio="SIC (Oficial)",
                        )
                    )

        return items
