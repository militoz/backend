#!/usr/bin/env python3
"""
CLI de Colombia Radar.
Comandos disponibles:
- descubrir [url] : inspecciona una URL y descubre feeds RSS/Atom o metadatos.
- probar <id>     : prueba un colector específico de sources.yaml y registra su salud.
- recolectar      : ejecuta recolección sobre todas las fuentes activas.
- analizar        : analiza artículos y genera señales/clusters.
- ciclo           : recolectar + guardar + analizar + limpiar demo (--estricto: falla si casi nada se recolectó).
- exportar        : escribe senales.json, macro.json, salud.json y meta.json (formato de la interfaz).
- servir          : inicia el servidor local Flask.
- todo            : ejecuta ciclo y arranca el servidor.
- evaluar         : evalúa desempeño comparando señales con feedback de analistas.
- historico       : (Punto 5) backfill de noticias pasadas reanudable con paginación.
- importar-emisores : (Punto 7) fusiona emisores desde CSV a config/empresas.yaml sin pisar alias.
"""
import sys
import os
import argparse
import yaml
import json
import csv
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Any, List

from radar.db import Database
from radar.fetch import Fetcher
from radar.collectors import construir, Item
from radar.pipeline import recolectar, guardar, analizar, limpiar, evaluar_estricto
from radar.export import exportar, exportar_base_publica


def cargar_yaml(rel_path: str) -> Dict[str, Any]:
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(__file__)
    ruta = os.path.abspath(os.path.join(base, rel_path))
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def guardar_yaml(rel_path: str, data: Dict[str, Any]):
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(__file__)
    ruta = os.path.abspath(os.path.join(base, rel_path))
    with open(ruta, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


# --- COMANDOS ---

def cmd_descubrir(args):
    url = args.url
    fetcher = Fetcher(user_agent="ColombiaRadar/1.0")
    print(f"[*] Inspeccionando URL: {url}")

    if not fetcher.permite_robots(url):
        print(f"[!] AVISO: robots.txt no permite el rastreo de {url}")
        return

    status, body, headers = fetcher.get(url, use_cache=False)
    print(f"[*] Código de respuesta: {status}")
    print(f"[*] Content-Type: {headers.get('Content-Type') or headers.get('content-type')}")

    if body:
        texto = body.decode("utf-8", errors="replace")
        # Buscar enlaces a RSS/Atom en el <head>
        feeds = re.findall(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']', texto, re.IGNORECASE)
        if not feeds:
            feeds = re.findall(r'<a[^>]+href=["\']([^"\']*(?:rss|feed|atom)[^"\']*)["\']', texto, re.IGNORECASE)

        if feeds:
            print("[+] Feeds descubiertos:")
            for f in set(feeds):
                f_abs = urllib.parse.urljoin(url, f)
                print(f"    - {f_abs}")
        else:
            print("[-] No se encontraron feeds RSS/Atom evidentes en el documento HTML.")


def cmd_probar(args):
    fuente_id = args.id
    cfg = cargar_yaml("config/sources.yaml")
    fuentes = cfg.get("fuentes", [])

    f_cfg = next((f for f in fuentes if f.get("id") == fuente_id), None)
    if not f_cfg:
        print(f"[!] Error: No se encontró la fuente '{fuente_id}' en config/sources.yaml")
        sys.exit(1)

    print(f"[*] Probando colector '{fuente_id}' (tipo: {f_cfg.get('tipo')}, url: {f_cfg.get('url')})")
    db = Database("radar.db")
    fetcher = Fetcher(db=db)

    colector = construir(f_cfg)
    if not colector:
        print(f"[!] Error: No se pudo construir el colector para tipo '{f_cfg.get('tipo')}'")
        sys.exit(1)

    try:
        items = colector.recolectar(fetcher)
        print(f"[+] Éxito: {len(items)} items recolectados.")
        for idx, it in enumerate(items[:5], 1):
            hint_str = f" [empresa_hint: {it.empresa_hint}]" if it.empresa_hint else ""
            print(f"    {idx}. [{it.certeza.upper()}]{hint_str} {it.titulo}")
            print(f"       URL: {it.url}")
            if it.resumen:
                print(f"       Resumen: {it.resumen[:120]}...")

        # Registrar en fuente_salud (Regla 6)
        db.registrar_salud(
            fuente_id=fuente_id,
            items_recolectados=len(items),
            exito=True,
            motivo_error="",
        )
        print("[+] Registro de salud actualizado en fuente_salud (estado: ok).")

    except Exception as e:
        print(f"[!] Fallo al recolectar de '{fuente_id}': {e}")
        db.registrar_salud(
            fuente_id=fuente_id,
            items_recolectados=0,
            exito=False,
            motivo_error=str(e),
        )
        print("[!] Registro de salud actualizado en fuente_salud (estado: error).")


def cmd_recolectar(args):
    db = Database("radar.db")
    cfg = cargar_yaml("config/sources.yaml")
    fetcher = Fetcher(db=db)
    print("[*] Iniciando recolección de fuentes activas...")
    items = recolectar(cfg, fetcher, db)
    guardados = guardar(items, db)
    print(f"[+] Recolección finalizada: {len(items)} items obtenidos, {guardados} nuevos o actualizados en articulos.")


def cmd_analizar(args):
    db = Database("radar.db")
    cfg = cargar_yaml("config/sources.yaml")
    fetcher = Fetcher(db=db)
    print("[*] Analizando artículos para detección de señales y eventos...")
    senales = analizar(db, cfg, fetcher=fetcher)
    print(f"[+] Análisis completado: {len(senales)} señales generadas o actualizadas.")


def cmd_ciclo(args):
    db = Database("radar.db")
    cfg = cargar_yaml("config/sources.yaml")
    fetcher = Fetcher(db=db)
    print("=== INICIANDO CICLO COMPLETO DE RADAR ===")
    stats = {}
    items = recolectar(cfg, fetcher, db, estadisticas=stats)
    guardar(items, db)
    analizar(db, cfg, fetcher=fetcher)
    borrados_demo = limpiar(db)
    print(f"=== CICLO COMPLETADO (Demo limpiados: {borrados_demo}) ===")

    activas = stats.get("fuentes_activas", 0)
    print(f"[*] Fuentes activas: {activas} | con respuesta: {stats.get('fuentes_ok', 0)} | con error: {stats.get('fuentes_error', 0)} | items: {stats.get('items', 0)}")
    for fid, det in stats.get("detalle", {}).items():
        if not det["ok"]:
            print(f"    [X] {fid}: {det['motivo']}")

    # Una ejecución "verde" que no recolectó nada es una falla escondida: con --estricto sale con error.
    if getattr(args, "estricto", False):
        problema = evaluar_estricto(stats, float(getattr(args, "min_fuentes_ok", 0.5)))
        if problema:
            print(f"[!] CICLO FALLIDO (modo estricto): {problema}")
            sys.exit(1)


def cmd_exportar(args):
    db = Database("radar.db")
    cfg = cargar_yaml("config/sources.yaml")
    rutas = exportar(db, cfg, args.salida)
    print(f"[+] Archivos escritos en '{args.salida}':")
    for nombre, ruta in rutas.items():
        print(f"    - {ruta}")
    if args.base_publica:
        res = exportar_base_publica("radar.db", args.base_publica)
        print(
            f"[+] Base pública escrita en '{args.base_publica}' "
            f"(texto de {res['articulos_sin_texto']} artículos y {res['cache_http_borrado']} páginas en caché eliminado)."
        )


def cmd_servir(args):
    from radar.server import run_server
    print(f"[*] Iniciando servidor local en http://{args.host}:{args.port}")
    run_server(host=args.host, port=args.port, debug=args.debug)


def cmd_todo(args):
    cmd_ciclo(args)
    cmd_servir(args)


def cmd_evaluar(args):
    db = Database("radar.db")
    feedback = db.obtener_feedback()
    print(f"[*] Total votos de feedback registrados: {len(feedback)}")
    utiles = sum(1 for f in feedback if f.get("util") == 1)
    no_utiles = sum(1 for f in feedback if f.get("util") == 0)
    precision = (utiles / len(feedback) * 100) if feedback else 0.0
    print(f"    - Útiles para investigar: {utiles}")
    print(f"    - No útiles: {no_utiles}")
    print(f"    - Precisión subjetiva: {precision:.1f}%")


# --- PUNTO 5: BACKFILL HISTÓRICO ---
def cmd_historico(args):
    """
    Punto 5: Backfill histórico con fuente de archivo (GDELT DOC 2.0 API).
    Parámetros configurables con límites respetados y reanudable.
    """
    desde = args.desde
    hasta = args.hasta or datetime.utcnow().strftime("%Y-%m-%d")
    query = args.query or "Colombia (empresa OR inversion OR adquisicion OR bancolombia OR ecopetrol)"
    max_records = int(args.max_records or 75)

    db = Database("radar.db")
    fetcher = Fetcher(db=db)

    # Comprobar estado previo para reanudación
    estado_previo = db.obtener_backfill_estado("gdelt_historico")
    fecha_actual_str = desde
    if estado_previo and estado_previo.get("ultima_fecha"):
        print(f"[*] Reanudando backfill desde la última fecha guardada: {estado_previo['ultima_fecha']}")
        fecha_actual_str = estado_previo["ultima_fecha"]

    dt_actual = datetime.strptime(fecha_actual_str, "%Y-%m-%d")
    dt_final = datetime.strptime(hasta, "%Y-%m-%d")

    print(f"[*] Iniciando backfill histórico desde {dt_actual.strftime('%Y-%m-%d')} hasta {hasta}...")
    articulos_totales = 0

    while dt_actual <= dt_final:
        dia_inicio_str = dt_actual.strftime("%Y%m%d") + "000000"
        dia_fin_str = dt_actual.strftime("%Y%m%d") + "235959"

        # VERIFICAR: Parámetros y límites de la API DOC 2.0 de GDELT:
        # - query string encodeada
        # - maxrecords (máximo permitido por GDELT suele ser 250)
        # - sourcecountry:CO
        # - format:json
        q_enc = urllib.parse.quote(query)
        url_gdelt = (
            f"https://api.gdeltproject.org/api/v2/doc/doc?"
            f"query={q_enc}%20sourcecountry:CO&mode=artlist&maxrecords={max_records}&"
            f"startdatetime={dia_inicio_str}&enddatetime={dia_fin_str}&format=json"
        )

        print(f"    -> Consultando ventana: {dt_actual.strftime('%Y-%m-%d')}")
        status, body, _ = fetcher.get(url_gdelt, min_delay=2.5, use_cache=True)

        items_dia = []
        if status == 200 and body:
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
                articles = data.get("articles", [])
                for a in articles:
                    title = a.get("title", "")
                    link = a.get("url", "")
                    seendate = a.get("seendate", "")
                    source = a.get("domain", "GDELT Colombia")

                    fecha_formato = dt_actual.strftime("%Y-%m-%d")
                    if seendate and len(seendate) >= 8:
                        fecha_formato = f"{seendate[:4]}-{seendate[4:6]}-{seendate[6:8]}"

                    if title and link:
                        items_dia.append(
                            Item(
                                titulo=title,
                                url=link,
                                fecha=fecha_formato,
                                resumen=f"Artículo histórico archivado vía GDELT ({source}).",
                                fuente_id="gdelt_historico",
                                certeza="probable",
                                medio=source,
                            )
                        )
            except Exception as e:
                print(f"       [!] Error decodificando respuesta de GDELT para {dt_actual.strftime('%Y-%m-%d')}: {e}")

        guardados = guardar(items_dia, db)
        articulos_totales += guardados
        print(f"       Items encontrados: {len(items_dia)}, guardados: {guardados}")

        # Guardar progreso para que sea reanudable
        db.guardar_backfill_estado("gdelt_historico", dt_actual.strftime("%Y-%m-%d"), "")

        # Avanzar al siguiente día
        dt_actual += timedelta(days=1)

    print(f"[+] Backfill histórico completado. Total artículos guardados: {articulos_totales}")


# --- PUNTO 7: IMPORTAR Y FUSIONAR EMISORES ---
def cmd_importar_emisores(args):
    """
    Punto 7: Lee un CSV oficial de emisores (nombre, ticker, sector, NIT opcional).
    Fusiona con config/empresas.yaml sin duplicar ni pisar alias manuales.
    Genera alias razonables (sin S.A., S.A.S., Ltda.) cuidando mayúsculas y nombres ambiguos.
    """
    archivo_csv = args.archivo
    if not os.path.exists(archivo_csv):
        print(f"[!] Error: No se encontró el archivo '{archivo_csv}'")
        sys.exit(1)

    cfg_actual = cargar_yaml("config/empresas.yaml")
    empresas_existentes = cfg_actual.get("empresas", [])

    # Indexar empresas existentes por nombre normalizado y ticker
    existentes_por_nombre = {e["nombre"].strip().lower(): e for e in empresas_existentes}
    existentes_por_ticker = {e["ticker"].strip().upper(): e for e in empresas_existentes if e.get("ticker")}

    nuevas_agregadas = 0
    actualizadas = 0

    with open(archivo_csv, "r", encoding="utf-8", errors="replace") as f:
        # Detectar delimitador (coma o punto y coma)
        muestra = f.read(2048)
        f.seek(0)
        delim = ";" if ";" in muestra and muestra.count(";") > muestra.count(",") else ","
        reader = csv.DictReader(f, delimiter=delim)

        # Mapear columnas de forma flexible
        field_map = {}
        for fn in (reader.fieldnames or []):
            fn_low = fn.lower().strip()
            if "nombre" in fn_low or "razon" in fn_low or "emisor" in fn_low:
                field_map["nombre"] = fn
            elif "ticker" in fn_low or "nemo" in fn_low or "simbolo" in fn_low:
                field_map["ticker"] = fn
            elif "sector" in fn_low or "actividad" in fn_low:
                field_map["sector"] = fn
            elif "nit" in fn_low:
                field_map["nit"] = fn

        for row in reader:
            nombre_raw = (row.get(field_map.get("nombre", "")) or "").strip()
            if not nombre_raw:
                continue

            ticker = (row.get(field_map.get("ticker", "")) or "").strip().upper() or None
            sector = (row.get(field_map.get("sector", "")) or "").strip() or "General"
            nit = (row.get(field_map.get("nit", "")) or "").strip() or None

            # Buscar si ya existe por nombre o ticker
            emp_existente = existentes_por_nombre.get(nombre_raw.lower())
            if not emp_existente and ticker:
                emp_existente = existentes_por_ticker.get(ticker)

            if emp_existente:
                # Actualizar campos aditivos sin pisar alias manuales
                if ticker and not emp_existente.get("ticker"):
                    emp_existente["ticker"] = ticker
                if nit and not emp_existente.get("nit"):
                    emp_existente["nit"] = nit
                if sector and (not emp_existente.get("sector") or emp_existente.get("sector") == "General"):
                    emp_existente["sector"] = sector
                actualizadas += 1
            else:
                # Generar alias razonables sin sufijos corporativos
                alias_generados = set()

                # Remover sufijos corporativos comunes (S.A., S.A.S., Ltda., E.S.P., etc.)
                limpio = re.sub(r"\b(?:S\.?A\.?S?|LTDA\.?|E\.?S\.?P\.?|INC\.?|CORP\.?|SOCIEDAD ANONIMA)\b", "", nombre_raw, flags=re.IGNORECASE)
                limpio = " ".join(limpio.split()).strip(" ,.-")

                # Cuidar nombres ambiguos: si el alias resultante tiene menos de 4 letras y no es un ticker explícito, evitar alias ambiguo
                if len(limpio) >= 4 and limpio.lower() != nombre_raw.lower():
                    alias_generados.add(limpio)

                nueva_emp = {
                    "nombre": nombre_raw,
                    "sector": sector,
                    "alias": sorted(list(alias_generados)),
                }
                if ticker:
                    nueva_emp["ticker"] = ticker
                if nit:
                    nueva_emp["nit"] = nit

                empresas_existentes.append(nueva_emp)
                existentes_por_nombre[nombre_raw.lower()] = nueva_emp
                if ticker:
                    existentes_por_ticker[ticker] = nueva_emp
                nuevas_agregadas += 1

    # Guardar en config/empresas.yaml
    cfg_actual["empresas"] = empresas_existentes
    guardar_yaml("config/empresas.yaml", cfg_actual)

    print(f"[+] Fusión de emisores completada:")
    print(f"    - Nuevas empresas agregadas: {nuevas_agregadas}")
    print(f"    - Empresas existentes actualizadas (ticker/nit/sector): {actualizadas}")
    print(f"    - Total empresas en catálogo: {len(empresas_existentes)}")


def main():
    parser = argparse.ArgumentParser(description="Colombia Radar CLI")
    subparsers = parser.add_subparsers(dest="comando", help="Comando a ejecutar")

    # descubrir
    p_descubrir = subparsers.add_parser("descubrir", help="Inspecciona URL y descubre feeds")
    p_descubrir.add_argument("url", help="URL a inspeccionar")

    # probar
    p_probar = subparsers.add_parser("probar", help="Prueba un colector de sources.yaml por ID")
    p_probar.add_argument("id", help="ID de la fuente en sources.yaml")

    # recolectar
    subparsers.add_parser("recolectar", help="Recolecta noticias de fuentes activas")

    # analizar
    subparsers.add_parser("analizar", help="Analiza artículos y genera señales")

    # ciclo
    p_ciclo = subparsers.add_parser("ciclo", help="Ejecuta ciclo completo (recolectar, guardar, analizar, limpiar)")
    p_ciclo.add_argument("--estricto", action="store_true", help="Sale con error si no se recolectó nada o casi todas las fuentes fallaron")
    p_ciclo.add_argument("--min-fuentes-ok", type=float, default=0.5, help="Fracción mínima de fuentes que deben responder (modo estricto)")

    # exportar
    p_exp = subparsers.add_parser("exportar", help="Escribe senales.json, macro.json, salud.json y meta.json")
    p_exp.add_argument("--salida", default="salida/data", help="Carpeta de salida de los JSON")
    p_exp.add_argument("--base-publica", default=None, help="Ruta donde escribir una copia de la base sin texto de medios")

    # servir
    p_servir = subparsers.add_parser("servir", help="Inicia el servidor Flask")
    p_servir.add_argument("--host", default="127.0.0.1", help="Host de escucha")
    p_servir.add_argument("--port", type=int, default=5000, help="Puerto de escucha")
    p_servir.add_argument("--debug", action="store_true", help="Modo debug")

    # todo
    p_todo = subparsers.add_parser("todo", help="Ejecuta ciclo y arranca servidor")
    p_todo.add_argument("--host", default="127.0.0.1")
    p_todo.add_argument("--port", type=int, default=5000)
    p_todo.add_argument("--debug", action="store_true")

    # evaluar
    subparsers.add_parser("evaluar", help="Evalúa señales según feedback")

    # historico (Punto 5)
    p_hist = subparsers.add_parser("historico", help="Backfill histórico de noticias")
    p_hist.add_argument("--desde", required=True, help="Fecha inicio AAAA-MM-DD")
    p_hist.add_argument("--hasta", default=None, help="Fecha fin AAAA-MM-DD")
    p_hist.add_argument("--query", default=None, help="Consulta de búsqueda")
    p_hist.add_argument("--max-records", default=75, help="Límite por ventana")

    # importar-emisores (Punto 7)
    p_imp = subparsers.add_parser("importar-emisores", help="Importa emisores oficiales desde CSV")
    p_imp.add_argument("archivo", help="Ruta al archivo CSV")

    args = parser.parse_args()

    if args.comando == "descubrir":
        cmd_descubrir(args)
    elif args.comando == "probar":
        cmd_probar(args)
    elif args.comando == "recolectar":
        cmd_recolectar(args)
    elif args.comando == "analizar":
        cmd_analizar(args)
    elif args.comando == "ciclo":
        cmd_ciclo(args)
    elif args.comando == "exportar":
        cmd_exportar(args)
    elif args.comando == "servir":
        cmd_servir(args)
    elif args.comando == "todo":
        cmd_todo(args)
    elif args.comando == "evaluar":
        cmd_evaluar(args)
    elif args.comando == "historico":
        cmd_historico(args)
    elif args.comando == "importar-emisores":
        cmd_importar_emisores(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
