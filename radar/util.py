"""
Utilidades compartidas: fechas, slugs, dominios y hashes cortos.
Regla de oro: si un dato no se puede interpretar, se devuelve None; nunca se inventa.
"""
import hashlib
import re
import unicodedata
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional


def normalizar_fecha(valor) -> Optional[str]:
    """
    Convierte fechas ISO o RFC 822 (las de los feeds RSS) a 'AAAA-MM-DDTHH:MM:SSZ' en UTC.
    Devuelve None si no se puede interpretar. Una fecha sin zona horaria se toma como UTC.
    """
    if not valor or not isinstance(valor, str):
        return None
    v = valor.strip()
    if not v:
        return None

    dt = None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00") if v.endswith("Z") else v)
    except ValueError:
        dt = None
    if dt is None:
        try:
            dt = parsedate_to_datetime(v)
        except (TypeError, ValueError, IndexError):
            dt = None
    if dt is None:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def semana_iso(fecha_iso: Optional[str]) -> Optional[str]:
    """'2026-09-30T14:15:00Z' -> '2026-w40'. None si no hay fecha válida."""
    norm = normalizar_fecha(fecha_iso) if fecha_iso else None
    if not norm:
        return None
    dt = datetime.strptime(norm[:10], "%Y-%m-%d")
    iso = dt.isocalendar()
    return f"{iso[0]}-w{iso[1]:02d}"


def slug(texto: Optional[str]) -> str:
    """Texto -> 'minusculas-sin-tildes-con-guiones'."""
    if not texto:
        return "sin-dato"
    base = unicodedata.normalize("NFKD", texto)
    base = "".join(c for c in base if not unicodedata.combining(c)).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "sin-dato"


def hash_corto(texto: str, largo: int = 6) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:largo]


def dominio(url: Optional[str]) -> Optional[str]:
    """'https://www.larepublica.co/x' -> 'larepublica.co'. None si no hay dominio."""
    if not url:
        return None
    host = urllib.parse.urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None
