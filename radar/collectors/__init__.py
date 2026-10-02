"""
Fábrica de colectores para Colombia Radar.
"""
from typing import Dict, Any, Optional
from .base import Collector, Item
from .gnews import GNewsCollector
from .rss import RssCollector
from .html import HtmlCollector
from .sitemap import SitemapCollector
from .superfinanciera import SuperfinancieraCollector
from .bvc import BvcCollector
from .sic import SicCollector
from .supersociedades import SupersociedadesCollector
from .serie import SerieCollector


def construir(cfg: Dict[str, Any]) -> Optional[Collector]:
    """Instancia el colector correspondiente según el campo 'tipo' en la configuración."""
    tipo = (cfg.get("tipo") or "rss").lower().strip()

    if tipo == "gnews":
        return GNewsCollector(cfg)
    elif tipo == "rss" or tipo == "atom":
        return RssCollector(cfg)
    elif tipo == "html":
        return HtmlCollector(cfg)
    elif tipo == "sitemap":
        return SitemapCollector(cfg)
    elif tipo == "superfinanciera":
        return SuperfinancieraCollector(cfg)
    elif tipo == "bvc":
        return BvcCollector(cfg)
    elif tipo == "sic":
        return SicCollector(cfg)
    elif tipo == "supersociedades":
        return SupersociedadesCollector(cfg)
    elif tipo == "serie":
        return SerieCollector(cfg)
    else:
        # Fallback a RSS por compatibilidad
        return RssCollector(cfg)


__all__ = [
    "Collector",
    "Item",
    "GNewsCollector",
    "RssCollector",
    "HtmlCollector",
    "SitemapCollector",
    "SuperfinancieraCollector",
    "BvcCollector",
    "SicCollector",
    "SupersociedadesCollector",
    "SerieCollector",
    "construir",
]
