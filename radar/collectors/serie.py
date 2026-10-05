"""
Colector para series macroeconómicas e insumos agrícolas (Punto 4).
Consulta APIs JSON o endpoints CSV (ej. Socrata datos.gov.co, BanRep, DANE).
Guarda en la tabla 'series' y emite señales de evento macro si la variación supera el umbral configurable.
"""
from typing import List, Optional, Dict, Any
import json
import csv
import io
from datetime import datetime
from .base import Collector, Item


class SerieCollector(Collector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "")
        self.serie_id = config.get("serie_id", config.get("id", "serie_generica"))
        self.formato = config.get("formato", "json")  # 'json' o 'csv'
        self.campo_fecha = config.get("campo_fecha", "vigenciadesde")
        self.campo_valor = config.get("campo_valor", "valor")
        self.umbral_variacion_pct = float(config.get("umbral_variacion_pct", 1.5))  # % de variación para disparar evento
        self.tipo_senal = config.get("tipo_senal", "macro")  # 'macro' o 'insumo'
        self.etiqueta_nombre = config.get("etiqueta_nombre", self.serie_id.upper())
        self.insumo_nombre = config.get("insumo_nombre")
        self.unidad = config.get("unidad", "")
        # Cuántos datos válidos leyó en la última corrida. Sirve para el reporte de salud:
        # una serie puede traer 0 EVENTOS (el dólar no se movió lo suficiente) y estar sana.
        self.puntos_leidos = 0

    def recolectar(self, fetcher) -> List[Item]:
        self.puntos_leidos = 0
        if not self.url:
            return []

        status, body, _ = fetcher.get(self.url, min_delay=self.min_delay)
        if status != 200 or not body:
            return []

        items_puntos: List[Dict[str, Any]] = []

        if self.formato == "json":
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
                if isinstance(data, list):
                    for fila in data:
                        f = str(fila.get(self.campo_fecha, "")).strip()
                        v_raw = fila.get(self.campo_valor)
                        if f and v_raw is not None:
                            try:
                                v = float(str(v_raw).replace(",", ".").replace("$", "").strip())
                                items_puntos.append({"fecha": f[:10], "valor": v})
                            except ValueError:
                                continue
            except Exception:
                return []
        elif self.formato == "csv":
            try:
                reader = csv.DictReader(io.StringIO(body.decode("utf-8", errors="replace")))
                for fila in reader:
                    f = str(fila.get(self.campo_fecha, "")).strip()
                    v_raw = fila.get(self.campo_valor)
                    if f and v_raw is not None:
                        try:
                            v = float(str(v_raw).replace(",", ".").replace("$", "").strip())
                            items_puntos.append({"fecha": f[:10], "valor": v})
                        except ValueError:
                            continue
            except Exception:
                return []

        if not items_puntos:
            return []

        self.puntos_leidos = len(items_puntos)

        # Ordenar por fecha ascendente
        items_puntos.sort(key=lambda x: x["fecha"])

        # Guardar en base de datos si fetcher tiene acceso a db
        if fetcher.db:
            for p in items_puntos:
                fetcher.db.guardar_serie_valor(self.serie_id, p["fecha"], p["valor"])

        # Evaluar variación respecto al valor anterior para generar evento macro
        ultimos = items_puntos[-2:] if len(items_puntos) >= 2 else items_puntos
        evento_items: List[Item] = []

        if len(ultimos) >= 2:
            prev = ultimos[0]
            actual = ultimos[1]
            if prev["valor"] != 0:
                var_pct = ((actual["valor"] - prev["valor"]) / prev["valor"]) * 100.0
                if abs(var_pct) >= self.umbral_variacion_pct:
                    signo = "+" if var_pct > 0 else ""
                    movimiento = "sube" if var_pct > 0 else "cae"
                    titulo = (
                        f"Señal Macro: {self.etiqueta_nombre} {movimiento} {signo}{var_pct:.2f}% "
                        f"situándose en {actual['valor']} {self.unidad} (fecha {actual['fecha']})"
                    )
                    resumen = (
                        f"La serie oficial {self.serie_id} registró una variación de {signo}{var_pct:.2f}%, "
                        f"superando el umbral de alerta de {self.umbral_variacion_pct}%. "
                        f"Valor anterior: {prev['valor']} ({prev['fecha']}) → Valor actual: {actual['valor']} ({actual['fecha']})."
                    )

                    evento_items.append(
                        Item(
                            titulo=titulo,
                            url=f"{self.url}#punto-{actual['fecha']}",
                            fecha=actual["fecha"],
                            resumen=resumen,
                            fuente_id=self.fuente_id,
                            certeza="confirmado",
                            medio=f"Datos Abiertos ({self.serie_id})",
                            metadata={
                                "serie_id": self.serie_id,
                                "valor_actual": actual["valor"],
                                "valor_anterior": prev["valor"],
                                "variacion_pct": var_pct,
                                "es_evento_macro": True,
                                "tipo_senal": self.tipo_senal,
                                "insumo": self.insumo_nombre,
                            },
                        )
                    )
        elif len(ultimos) == 1:
            # Emitir item de referencia para visibilidad en primera corrida
            actual = ultimos[0]
            evento_items.append(
                Item(
                    titulo=f"Serie {self.etiqueta_nombre}: {actual['valor']} {self.unidad} ({actual['fecha']})",
                    url=f"{self.url}#punto-{actual['fecha']}",
                    fecha=actual["fecha"],
                    resumen=f"Punto base registrado para la serie {self.serie_id}.",
                    fuente_id=self.fuente_id,
                    certeza="confirmado",
                    medio="Datos Abiertos",
                    metadata={"serie_id": self.serie_id, "valor": actual["valor"], "es_evento_macro": False},
                )
            )

        return evento_items
