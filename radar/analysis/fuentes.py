"""
Ayudas para interpretar la configuración de fuentes (sources.yaml):
certeza declarada, nombre del medio y tipo de fuente de cada artículo.
"""
from typing import Any, Dict, Iterable, List, Optional

from ..util import dominio

# De menor a mayor confianza. Una señal toma la certeza más alta de sus notas.
RANGO_CERTEZA = {"rumor": 0, "probable": 1, "confirmado": 2, "oficial": 3}

# Dominios que solo son intermediarios: no sirven como nombre de medio.
DOMINIOS_INTERMEDIARIOS = {"news.google.com"}

TIPOS_OFICIALES = {"superfinanciera", "bvc", "sic", "supersociedades"}


def mapa_fuentes(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{fuente_id: configuración de la fuente en sources.yaml}"""
    return {f.get("id"): f for f in (cfg or {}).get("fuentes", []) if f.get("id")}


def certeza_de_articulo(art: Dict[str, Any], mapa: Dict[str, Dict[str, Any]]) -> str:
    """
    Certeza de una nota. Manda la declarada en sources.yaml para su fuente;
    si la fuente no está allí, la guardada con el artículo; si no hay nada, 'probable'.
    """
    declarada = (mapa.get(art.get("fuente_id")) or {}).get("certeza")
    for candidato in (declarada, art.get("certeza")):
        if candidato and str(candidato).lower() in RANGO_CERTEZA:
            return str(candidato).lower()
    return "probable"


def certeza_mayor(certezas: Iterable[str]) -> str:
    lista = [c for c in certezas if c in RANGO_CERTEZA]
    if not lista:
        return "probable"
    return max(lista, key=lambda c: RANGO_CERTEZA[c])


def resolver_medio(art: Dict[str, Any], mapa: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """
    Nombre del medio de una nota, sin inventar:
    1) el medio guardado con la nota, 2) el 'medio' de la fuente en sources.yaml,
    3) el dominio de la URL (salvo intermediarios), 4) el nombre de la fuente. Si nada, None.
    """
    medio = (art.get("medio") or "").strip()
    if medio:
        return medio
    f_cfg = mapa.get(art.get("fuente_id")) or {}
    medio = (f_cfg.get("medio") or "").strip()
    if medio:
        return medio
    dom = dominio(art.get("url"))
    if dom and dom not in DOMINIOS_INTERMEDIARIOS:
        return dom
    nombre = (f_cfg.get("nombre") or "").strip()
    return nombre or None


def tipo_de_fuente(f_cfg: Dict[str, Any]) -> str:
    """'oficial', 'prensa' o 'serie' (datos abiertos), según el colector."""
    tipo = (f_cfg or {}).get("tipo", "")
    if tipo in TIPOS_OFICIALES or (f_cfg or {}).get("certeza") == "confirmado" and tipo in {"html", "rss"}:
        return "oficial"
    if tipo == "serie":
        return "serie"
    return "prensa"
