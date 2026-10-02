"""
Extracción y vinculación de entidades (Empresas e Insumos).
Soporta 'empresa_hint' desde fuentes oficiales para vinculación directa.
"""
from typing import List, Dict, Any, Tuple, Optional, Set
import re
import yaml
import os


def normalizar_texto(texto: str) -> str:
    """Elimina tildes y caracteres especiales para coincidencia flexible."""
    if not texto:
        return ""
    t = texto.lower()
    t = re.sub(r"[áäàâ]", "a", t)
    t = re.sub(r"[éëèê]", "e", t)
    t = re.sub(r"[íïìî]", "i", t)
    t = re.sub(r"[óöòô]", "o", t)
    t = re.sub(r"[úüùû]", "u", t)
    t = re.sub(r"[ñ]", "n", t)
    return t


class EntidadesDetector:
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None or config_dir == "config":
            # Intentar encontrar la carpeta config en el proyecto
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
        self.empresas: List[Dict[str, Any]] = []
        self.insumos: List[Dict[str, Any]] = []
        self.recargar()

    def recargar(self):
        emp_path = os.path.join(self.config_dir, "empresas.yaml")
        if os.path.exists(emp_path):
            with open(emp_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                self.empresas = data.get("empresas", [])

        ins_path = os.path.join(self.config_dir, "insumos.yaml")
        if os.path.exists(ins_path):
            with open(ins_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                self.insumos = data.get("insumos", [])

    def resolver_empresa_hint(self, hint: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Punto 1: Vincula directamente la señal a la empresa cuando empresa_hint coincide
        con alguna empresa de empresas.yaml (por nombre, ticker, nit o alias).
        """
        if not hint or not hint.strip():
            return None

        hint_norm = normalizar_texto(hint.strip())

        for emp in self.empresas:
            nombre = emp.get("nombre", "")
            if normalizar_texto(nombre) == hint_norm:
                return emp

            ticker = emp.get("ticker")
            if ticker and normalizar_texto(ticker) == hint_norm:
                return emp

            nit = emp.get("nit")
            if nit and str(nit).replace("-", "").strip() == hint.replace("-", "").strip():
                return emp

            for al in emp.get("alias", []):
                if normalizar_texto(al) == hint_norm:
                    return emp

        # Si no hay match exacto, verificar si el hint contiene el nombre o algún alias representativo
        for emp in self.empresas:
            for al in [emp.get("nombre", "")] + emp.get("alias", []):
                al_norm = normalizar_texto(al)
                if len(al_norm) >= 4 and al_norm in hint_norm:
                    return emp

        return None

    def detectar_empresas(self, texto: str, empresa_hint: Optional[str] = None) -> Tuple[List[str], List[str]]:
        """
        Retorna (lista_nombres_empresas, lista_sectores).
        Prioriza empresa_hint de fuentes oficiales si existe.
        """
        encontradas_set: Set[str] = set()
        sectores_set: Set[str] = set()

        # 1. Resolver empresa_hint primero (Punto 1)
        if empresa_hint:
            match_hint = self.resolver_empresa_hint(empresa_hint)
            if match_hint:
                encontradas_set.add(match_hint["nombre"])
                if match_hint.get("sector"):
                    sectores_set.add(match_hint["sector"])
            else:
                # Si no está en el catálogo, se puede incluir como entidad detectada sin clasificar
                encontradas_set.add(empresa_hint.strip())

        # 2. Búsqueda en el texto
        if texto:
            texto_norm = normalizar_texto(texto)
            for emp in self.empresas:
                nombre = emp.get("nombre", "")
                ticker = emp.get("ticker", "")
                alias_list = emp.get("alias", [])
                candidatos = [nombre] + alias_list
                if ticker:
                    candidatos.append(ticker)

                for cand in candidatos:
                    cand_norm = normalizar_texto(cand)
                    if not cand_norm or len(cand_norm) < 3:
                        continue

                    # Coincidencia con límites de palabra para evitar falsos positivos
                    patron = rf"\b{re.escape(cand_norm)}\b"
                    if re.search(patron, texto_norm):
                        encontradas_set.add(nombre)
                        if emp.get("sector"):
                            sectores_set.add(emp["sector"])
                        break

        return list(encontradas_set), list(sectores_set)

    def detectar_insumos(self, texto: str) -> List[str]:
        """Detecta insumos o materias primas mencionadas en el texto."""
        encontrados: Set[str] = set()
        if not texto:
            return []

        texto_norm = normalizar_texto(texto)
        for ins in self.insumos:
            nombre = ins.get("nombre", "")
            for al in [nombre] + ins.get("alias", []):
                al_norm = normalizar_texto(al)
                if not al_norm or len(al_norm) < 3:
                    continue
                patron = rf"\b{re.escape(al_norm)}\b"
                if re.search(patron, texto_norm):
                    encontrados.add(nombre)
                    break

        return list(encontrados)
