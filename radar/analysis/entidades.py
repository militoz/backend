"""
Extracción y vinculación de entidades (Empresas e Insumos).
Soporta 'empresa_hint' desde fuentes oficiales para vinculación directa.
 
Cambios frente a la versión anterior:
- Regex precompiladas una sola vez en recargar() (antes se compilaban por cada texto).
- Siglas y tickers (GEB, ISA, ETB...) se buscan respetando mayúsculas sobre el texto original,
  para que "isa" o "geb" como palabra común no generen falsos positivos.
- Campo opcional `alias_ambiguos` en empresas.yaml: alias que son palabra común
  (p. ej. "Éxito"); solo cuentan si aparecen con mayúscula inicial (y, al inicio del texto,
  si no los sigue una preposición: "Éxito de ventas" no cuenta, "Éxito reporta" sí).
- Campo opcional `ticker_ambiguo: true`: el ticker solo se usa para resolver hints, no en texto.
- Soporta `ticker_preferencial` (PFCIBEST, PFAVAL...).
- Comparación de NIT solo por dígitos (ignora puntos, guiones y espacios).
- El fallback del hint usa límites de palabra (antes era una subcadena suelta).
- Resultado en orden estable (antes salía de un set, el orden cambiaba entre corridas).
- Advertencia en el log si no se encuentra empresas.yaml o viene vacío.
"""
from typing import List, Dict, Any, Tuple, Optional
import logging
import os
import re
import unicodedata
 
import yaml
 
log = logging.getLogger(__name__)
 
 
def _sin_tildes(texto: str) -> str:
    """Quita tildes y diéresis (ñ -> n) conservando mayúsculas/minúsculas."""
    if not texto:
        return ""
    d = unicodedata.normalize("NFD", texto)
    return "".join(c for c in d if unicodedata.category(c) != "Mn")
 
 
def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes ni ñ, para coincidencia flexible."""
    return _sin_tildes(texto).lower()
 
 
def _solo_digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))
 
 
def _es_sigla(cand: str) -> bool:
    """GEB, ISA, ETB, PFBCOLOM... (todo en mayúsculas, sin espacios, 2-10 caracteres)."""
    c = cand.strip()
    return 2 <= len(c) <= 10 and c.isupper() and re.fullmatch(r"[A-Z0-9&.]+", _sin_tildes(c)) is not None
 
 
# Palabras que, justo después de un alias ambiguo al inicio del texto, indican uso común
# ("Éxito de ventas...", "Mineros de Segovia...") y no el nombre de la empresa.
_STOP_SIGUIENTE = {"de", "del", "en", "para", "por", "con", "a", "al", "la", "las", "los",
                   "el", "y", "e", "o", "que", "como", "no", "sin", "sobre"}
 
 
def _ambiguo_valido(orig: str, norm: str, m: "re.Match") -> bool:
    """Alias ambiguo: debe llevar mayúscula inicial. Al inicio del texto (donde toda palabra va
    en mayúscula) solo vale si la palabra siguiente no es una preposición/artículo."""
    if not orig[m.start()].isupper():
        return False
    if m.start() > 0:
        return True
    sig = norm[m.end():].split()
    return not sig or sig[0].strip(",.;:") not in _STOP_SIGUIENTE
 
 
def _patron_palabra(norm: str, flags: int = 0) -> "re.Pattern":
    return re.compile(rf"(?<![a-z0-9]){re.escape(norm)}(?![a-z0-9])", flags)
 
 
class EntidadesDetector:
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
        self.empresas: List[Dict[str, Any]] = []
        self.insumos: List[Dict[str, Any]] = []
        self._pat_empresas: List[Tuple[Dict[str, Any], List[Tuple[str, "re.Pattern"]]]] = []
        self._pat_insumos: List[Tuple[str, List["re.Pattern"]]] = []
        self.recargar()
 
    # ------------------------------------------------------------------ carga
    def recargar(self):
        self.empresas, self.insumos = [], []
        emp_path = os.path.join(self.config_dir, "empresas.yaml")
        if os.path.exists(emp_path):
            with open(emp_path, "r", encoding="utf-8") as f:
                self.empresas = (yaml.safe_load(f) or {}).get("empresas", []) or []
        if not self.empresas:
            log.warning("empresas.yaml no encontrado o vacío en %s: no se detectarán empresas", self.config_dir)
 
        ins_path = os.path.join(self.config_dir, "insumos.yaml")
        if os.path.exists(ins_path):
            with open(ins_path, "r", encoding="utf-8") as f:
                self.insumos = (yaml.safe_load(f) or {}).get("insumos", []) or []
 
        self._compilar()
 
    def _compilar(self):
        """Precompila una regex por candidato. Tipo: 'norm' (minúsculas), 'sigla' o 'ambiguo'."""
        self._pat_empresas = []
        for emp in self.empresas:
            nombre = emp.get("nombre", "")
            ticker = emp.get("ticker") or ""
            ticker_pref = emp.get("ticker_preferencial") or ""
            tickers = {t for t in (ticker, ticker_pref) if t}
            # ticker_ambiguo: true -> el ticker coincide con otra sigla (p. ej. CNE = Consejo
            # Nacional Electoral); se usa para resolver hints pero no se busca en el texto.
            buscar_tickers = set() if emp.get("ticker_ambiguo") else tickers
            ambiguos = {normalizar_texto(a) for a in (emp.get("alias_ambiguos") or [])}
            pats: List[Tuple[str, "re.Pattern"]] = []
            vistos = set()
 
            candidatos = [nombre] + list(emp.get("alias") or []) + list(emp.get("alias_ambiguos") or [])
            candidatos.extend(sorted(buscar_tickers))
 
            for cand in candidatos:
                cand = (cand or "").strip()
                norm = normalizar_texto(cand)
                if len(norm) < 3 or cand in vistos:
                    continue
                vistos.add(cand)
                if cand in buscar_tickers or _es_sigla(cand):
                    pats.append(("sigla", re.compile(rf"(?<![A-Za-z0-9]){re.escape(_sin_tildes(cand))}(?![A-Za-z0-9])")))
                elif norm in ambiguos:
                    pats.append(("ambiguo", _patron_palabra(norm)))
                else:
                    pats.append(("norm", _patron_palabra(norm)))
            self._pat_empresas.append((emp, pats))
 
        self._pat_insumos = []
        for ins in self.insumos:
            nombre = ins.get("nombre", "")
            pats = []
            for al in [nombre] + list(ins.get("alias") or []):
                norm = normalizar_texto(al)
                if len(norm) >= 3:
                    pats.append(_patron_palabra(norm))
            self._pat_insumos.append((nombre, pats))
 
    # ------------------------------------------------------------------- hint
    def resolver_empresa_hint(self, hint: Optional[str]) -> Optional[Dict[str, Any]]:
        """Vincula la señal a una empresa de empresas.yaml por nombre, ticker, NIT o alias."""
        if not hint or not hint.strip():
            return None
 
        hint_norm = normalizar_texto(hint.strip())
        hint_dig = _solo_digitos(hint)
 
        for emp in self.empresas:
            if normalizar_texto(emp.get("nombre", "")) == hint_norm:
                return emp
            for t in (emp.get("ticker"), emp.get("ticker_preferencial")):
                if t and normalizar_texto(t) == hint_norm:
                    return emp
            nit = _solo_digitos(emp.get("nit"))
            # NIT: con o sin dígito de verificación
            if nit and hint_dig and (hint_dig == nit or hint_dig == nit[:-1] or hint_dig[:-1] == nit):
                return emp
            for al in (emp.get("alias") or []) + (emp.get("alias_ambiguos") or []):
                if normalizar_texto(al) == hint_norm:
                    return emp
 
        # Sin coincidencia exacta: el hint contiene el nombre o un alias (con límites de palabra)
        for emp in self.empresas:
            for al in [emp.get("nombre", "")] + list(emp.get("alias") or []):
                al_norm = normalizar_texto(al)
                if len(al_norm) >= 4 and _patron_palabra(al_norm).search(hint_norm):
                    return emp
        return None
 
    # ---------------------------------------------------------------- empresas
    def detectar_empresas(self, texto: str, empresa_hint: Optional[str] = None) -> Tuple[List[str], List[str]]:
        """Retorna (nombres_empresas, sectores) en orden estable. empresa_hint tiene prioridad."""
        encontradas: Dict[str, None] = {}
        sectores: Dict[str, None] = {}
 
        if empresa_hint:
            match_hint = self.resolver_empresa_hint(empresa_hint)
            if match_hint:
                encontradas[match_hint["nombre"]] = None
                if match_hint.get("sector"):
                    sectores[match_hint["sector"]] = None
            else:
                encontradas[empresa_hint.strip()] = None  # entidad fuera del catálogo, sin clasificar
 
        if texto:
            orig = _sin_tildes(texto)
            norm = orig.lower()
            for emp, pats in self._pat_empresas:
                for tipo, pat in pats:
                    if tipo == "sigla":
                        ok = bool(pat.search(orig))
                    elif tipo == "ambiguo":
                        # Con mayúscula inicial; al inicio del texto se descarta si sigue una preposición
                        ok = any(_ambiguo_valido(orig, norm, m) for m in pat.finditer(norm))
                    else:
                        ok = bool(pat.search(norm))
                    if ok:
                        encontradas[emp["nombre"]] = None
                        if emp.get("sector"):
                            sectores[emp["sector"]] = None
                        break
 
        return list(encontradas), list(sectores)
 
    # ----------------------------------------------------------------- insumos
    def detectar_insumos(self, texto: str) -> List[str]:
        """Detecta insumos o materias primas mencionadas en el texto."""
        if not texto:
            return []
        norm = normalizar_texto(texto)
        encontrados: Dict[str, None] = {}
        for nombre, pats in self._pat_insumos:
            if any(p.search(norm) for p in pats):
                encontrados[nombre] = None
        return list(encontrados)
 
