"""
Clases base y funciones auxiliares para colectores.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from abc import ABC, abstractmethod
import xml.etree.ElementTree as ET
import re
import html
from datetime import datetime


@dataclass
class Item:
    titulo: str
    url: str
    fecha: str
    resumen: Optional[str] = None
    extracto: Optional[str] = None
    certeza: str = "probable"
    fuente_id: str = ""
    empresa_hint: Optional[str] = None
    medio: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Collector(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.fuente_id = config.get("id", "")
        self.tipo = config.get("tipo", "rss")
        self.peso_confiabilidad = config.get("peso", 1.0)
        self.min_delay = config.get("min_delay", 1.0)

    @abstractmethod
    def recolectar(self, fetcher) -> List[Item]:
        """Recolecta items usando el fetcher proporcionado."""
        pass


def limpiar_html(raw_html: str) -> str:
    """Elimina etiquetas HTML y decodifica entidades para obtener texto limpio."""
    if not raw_html:
        return ""
    texto = re.sub(r"<[^>]+>", " ", raw_html)
    texto = html.unescape(texto)
    return " ".join(texto.split()).strip()


def parse_feed(xml_content: bytes, fuente_id: str, config: Optional[Dict[str, Any]] = None) -> List[Item]:
    """
    Parsea feeds RSS o Atom usando el módulo estándar xml.etree.ElementTree.
    Soporta extracción de titular, enlace, fecha, y resumen corto.
    """
    items: List[Item] = []
    if not xml_content:
        return items

    texto_xml = xml_content.decode("utf-8", errors="replace").strip()
    try:
        root = ET.fromstring(texto_xml)
    except ET.ParseError:
        # Fallback a búsqueda regex básica si hay XML malformado
        return _parse_feed_regex(texto_xml, fuente_id, config)

    medio = config.get("medio") if config else None
    certeza = config.get("certeza", "probable") if config else "probable"

    # Caso 1: RSS 2.0 / 0.9x (<rss><channel><item>...)
    channel = root.find("channel")
    if channel is not None:
        for it in channel.findall("item"):
            titulo = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub_date = (it.findtext("pubDate") or it.findtext("date") or "").strip()
            desc = it.findtext("description") or it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
            resumen_limpio = limpiar_html(desc)

            # Si el link viene en guids con isPermaLink=true
            if not link:
                guid = it.find("guid")
                if guid is not None and guid.get("isPermaLink") == "true":
                    link = (guid.text or "").strip()

            if titulo and link:
                items.append(
                    Item(
                        titulo=html.unescape(titulo),
                        url=link,
                        fecha=pub_date,
                        resumen=resumen_limpio if resumen_limpio else None,
                        fuente_id=fuente_id,
                        certeza=certeza,
                        medio=medio,
                    )
                )
        return items

    # Caso 2: Atom (<feed><entry>...)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns) or root.findall("entry"):
        titulo = (entry.findtext("atom:title", namespaces=ns) or entry.findtext("title") or "").strip()
        link_elem = entry.find("atom:link", ns) or entry.find("link")
        link = ""
        if link_elem is not None:
            link = link_elem.get("href", "").strip() or (link_elem.text or "").strip()
        fecha = (
            entry.findtext("atom:updated", namespaces=ns)
            or entry.findtext("atom:published", namespaces=ns)
            or entry.findtext("updated")
            or entry.findtext("published")
            or ""
        ).strip()
        summary = entry.findtext("atom:summary", namespaces=ns) or entry.findtext("summary") or ""
        resumen_limpio = limpiar_html(summary)

        if titulo and link:
            items.append(
                Item(
                    titulo=html.unescape(titulo),
                    url=link,
                    fecha=fecha,
                    resumen=resumen_limpio if resumen_limpio else None,
                    fuente_id=fuente_id,
                    certeza=certeza,
                    medio=medio,
                )
            )

    return items


def _parse_feed_regex(texto: str, fuente_id: str, config: Optional[Dict[str, Any]] = None) -> List[Item]:
    """Fallback ligero por expresiones regulares si el XML no es perfectamente estricto."""
    items = []
    item_blocks = re.findall(r"<item\b[^>]*>(.*?)</item>", texto, re.DOTALL | re.IGNORECASE)
    medio = config.get("medio") if config else None
    certeza = config.get("certeza", "probable") if config else "probable"

    for block in item_blocks:
        t_m = re.search(r"<title\b[^>]*>(.*?)</title>", block, re.DOTALL | re.IGNORECASE)
        l_m = re.search(r"<link\b[^>]*>(.*?)</link>", block, re.DOTALL | re.IGNORECASE)
        f_m = re.search(r"<(?:pubDate|date)\b[^>]*>(.*?)</(?:pubDate|date)>", block, re.DOTALL | re.IGNORECASE)
        d_m = re.search(r"<description\b[^>]*>(.*?)</description>", block, re.DOTALL | re.IGNORECASE)

        if t_m and l_m:
            titulo = limpiar_html(t_m.group(1))
            url = l_m.group(1).strip()
            fecha = f_m.group(1).strip() if f_m else ""
            resumen = limpiar_html(d_m.group(1)) if d_m else None
            items.append(
                Item(
                    titulo=titulo,
                    url=url,
                    fecha=fecha,
                    resumen=resumen,
                    fuente_id=fuente_id,
                    certeza=certeza,
                    medio=medio,
                )
            )
    return items
