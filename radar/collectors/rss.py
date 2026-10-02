"""
Colector genérico para feeds RSS y Atom.
"""
from typing import List
from .base import Collector, Item, parse_feed


class RssCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "")

    def recolectar(self, fetcher) -> List[Item]:
        if not self.url:
            return []

        status, body, _ = fetcher.get(self.url, min_delay=self.min_delay)
        if status != 200 or not body:
            return []

        return parse_feed(body, self.fuente_id, self.config)
