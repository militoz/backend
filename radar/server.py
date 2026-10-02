"""
Servidor web Flask para el tablero de control de Colombia Radar.
Rutas:
- / : Tablero principal con señales, noticias, series macro y aviso de fuentes degradadas.
- /api/salud : Estado de salud y degradación de fuentes (mismo formato que salud.json).
- /api/feedback : Registro de retroalimentación de analistas (útil / no útil).
- /api/senales : Lista de señales en JSON (mismo formato que senales.json).
- /api/macro : Series macroeconómicas y eventos macro (mismo formato que macro.json).
"""
from flask import Flask, render_template, jsonify, request
import os
import sys
import yaml
from .db import Database
from .export import construir_senales, construir_macro, construir_salud

if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

db = Database("radar.db")


def cargar_config_sources():
    cfg_path = os.path.join(BASE_DIR, "config", "sources.yaml")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@app.route("/")
def index():
    senales = db.obtener_senales(limit=40)
    articulos = db.obtener_articulos(limit=50, solo_no_demo=True)
    salud_fuentes = db.obtener_salud_fuentes()

    # Identificar fuentes degradadas para aviso en el tablero (Punto 6)
    fuentes_degradadas = [f for f in salud_fuentes if f.get("estado") == "degradada"]

    # Traer últimas observaciones de series macro
    series_resumen = {}
    for sid in ["trm", "tasa_politica", "ipc", "urea_bulto"]:
        puntos = db.obtener_ultimos_valores_serie(sid, limite=3)
        if puntos:
            series_resumen[sid] = puntos

    return render_template(
        "index.html",
        senales=senales,
        articulos=articulos,
        salud_fuentes=salud_fuentes,
        fuentes_degradadas=fuentes_degradadas,
        series_resumen=series_resumen,
    )


@app.route("/api/salud")
def api_salud():
    """Mismo formato que salud.json."""
    return jsonify(construir_salud(db, cargar_config_sources()))


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    data = request.get_json() or {}
    cluster_id = data.get("cluster_id")
    tipo = data.get("tipo", "general")
    util = int(data.get("util", 1))

    if cluster_id is not None:
        db.guardar_feedback(cluster_id=int(cluster_id), tipo=tipo, util=util)
        return jsonify({"ok": True, "mensaje": "Feedback registrado exitosamente"})
    return jsonify({"ok": False, "error": "Falta cluster_id"}), 400


@app.route("/api/senales")
def api_senales():
    """Mismo formato que senales.json."""
    return jsonify(construir_senales(db, cargar_config_sources()))


@app.route("/api/macro")
def api_macro():
    """Mismo formato que macro.json."""
    return jsonify(construir_macro(db, cargar_config_sources()))


def run_server(host="127.0.0.1", port=5000, debug=False):
    app.run(host=host, port=port, debug=debug)
