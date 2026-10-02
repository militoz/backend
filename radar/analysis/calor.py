"""
Cálculo de temperatura / score de calor de las señales:
temperatura = peso_tipo × certeza × factor_fuentes × factor_recencia

ESTA ES LA ÚNICA FÓRMULA DEL SCORE. La interfaz solo muestra lo que viene en los JSON
(score y scoreBreakdown); no la recalcula.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from ..util import normalizar_fecha


PESOS_CERTEZA = {
    "confirmado": 1.4,
    "oficial": 1.5,
    "probable": 1.1,
    "rumor": 0.7,
}


def desglosar_score(
    peso_tipo: float,
    certeza: str,
    n_fuentes: int,
    fecha_iso: Optional[str],
    ahora: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Devuelve el score y el desglose de cada factor.
    Claves: score, pesoTipo, pesoCerteza, pesoFuente, pesoRecencia,
    certezaDesconocida, fechaDesconocida.
    """
    ahora = ahora or datetime.utcnow()
    clave = (certeza or "").lower()
    certeza_desconocida = clave not in PESOS_CERTEZA
    p_certeza = PESOS_CERTEZA.get(clave, 1.0)

    # Factor de pluralidad de fuentes: escala suave
    f_fuentes = 0.9 + min(n_fuentes * 0.1, 0.5)

    # Factor de recencia (días de antigüedad)
    fecha_desconocida = False
    if not fecha_iso:
        f_recencia = 1.5
        fecha_desconocida = True
    else:
        norm = normalizar_fecha(fecha_iso)
        if norm is None:
            f_recencia = 1.2
            fecha_desconocida = True
        else:
            dt = datetime.strptime(norm[:10], "%Y-%m-%d")
            dias = max(0, (ahora - dt).days)
            f_recencia = max(0.5, 1.8 - min(dias / 30.0, 1.0) * 1.0)

    score = peso_tipo * p_certeza * f_fuentes * (f_recencia / 1.5)
    return {
        "score": round(score, 2),
        "pesoTipo": round(peso_tipo, 2),
        "pesoCerteza": round(p_certeza, 2),
        "pesoFuente": round(f_fuentes, 2),
        "pesoRecencia": round(f_recencia, 2),
        "certezaDesconocida": certeza_desconocida,
        "fechaDesconocida": fecha_desconocida,
    }


def calcular_score_calor(
    peso_tipo: float,
    certeza: str,
    n_fuentes: int,
    fecha_iso: str,
) -> float:
    """Calcula el score de calor normalizado (solo el número)."""
    return desglosar_score(peso_tipo, certeza, n_fuentes, fecha_iso)["score"]
