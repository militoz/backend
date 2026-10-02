"""
Detección de señales y eventos corporativos basados en reglas regex en config/eventos.yaml.
"""
from typing import List, Dict, Any, Optional
import re
import yaml
import os


class EventosDetector:
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None or config_dir == "config":
            base_cand1 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config"))
            base_cand2 = os.path.abspath("config")
            base_cand3 = os.path.abspath("colombia_radar/config")
            if os.path.exists(base_cand1):
                self.config_dir = base_cand1
            elif os.path.exists(base_cand3):
                self.config_dir = base_cand3
            else:
                self.config_dir = base_cand2
        else:
            self.config_dir = config_dir
        self.reglas: List[Dict[str, Any]] = []
        self.recargar()

    def recargar(self):
        path = os.path.join(self.config_dir, "eventos.yaml")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                self.reglas = data.get("eventos", [])

    def evaluar_texto(
        self,
        titulo: str,
        texto_ampliado: Optional[str] = None,
        es_macro: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Evalúa el texto contra las reglas configuradas.
        Si solo_titulo es False, evalúa tanto título como extracto/resumen.
        """
        coincidencias: List[Dict[str, Any]] = []

        texto_completo = f"{titulo} {texto_ampliado or ''}".strip()

        for regla in self.reglas:
            patron = regla.get("patron", "")
            if not patron:
                continue

            solo_titulo = regla.get("solo_titulo", True)
            texto_a_evaluar = titulo if solo_titulo else texto_completo

            try:
                match = re.search(patron, texto_a_evaluar, re.IGNORECASE)
                if match:
                    coincidencias.append(
                        {
                            "tipo": regla.get("tipo", "corporativo"),
                            "etiqueta": regla.get("etiqueta", regla.get("tipo")),
                            "peso_tipo": float(regla.get("peso", 1.0)),
                            "razonamiento": regla.get("razonamiento", "Evento corporativo detectado por coincidencia léxica."),
                            "match_texto": match.group(0),
                            "es_ambigua": regla.get("ambigua", False),
                        }
                    )
            except re.error:
                continue

        return coincidencias
