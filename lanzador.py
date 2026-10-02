#!/usr/bin/env python3
"""
Lanzador de escritorio para Colombia Radar (herramienta personal para PC).
Abre la aplicación como VENTANA NATIVA DE ESCRITORIO o MODO APLICACIÓN independiente (sin barras de navegador).

Prioridad de apertura:
1. 'pywebview' si está instalado (Ventana 100% nativa con motor WebView2/WebKit).
2. Modo App Dedicada (--app de Edge / Chrome / Brave) que abre una ventana sin pestañas ni barra de URL.
3. Fallback al navegador web convencional si no hay navegador compatible con modo app.
"""
import sys
import os
import subprocess
import threading
import time
import webbrowser
import platform

# Soporte para PyInstaller cuando se empaqueta en .exe
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS  # Directorio temporal de PyInstaller
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from radar.server import app


def encontrar_ejecutable_modo_app():
    """Busca navegadores compatibles con el flag --app para abrir una ventana nativa independiente."""
    sistema = platform.system().lower()

    if sistema == "windows":
        candidatos = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]
        for ruta in candidatos:
            if os.path.exists(ruta):
                return ruta

    elif sistema == "darwin":  # macOS
        candidatos = [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
        for ruta in candidatos:
            if os.path.exists(ruta):
                return ruta

    elif sistema == "linux":
        import shutil
        for comando in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"]:
            ruta = shutil.which(comando)
            if ruta:
                return ruta

    return None


def abrir_ventana_escritorio(url: str, delay: float = 1.0):
    time.sleep(delay)
    print(f"[*] Conectando a {url}")

    # 1. Intentar modo ventana de aplicación independiente (--app)
    ejecutable = encontrar_ejecutable_modo_app()
    if ejecutable:
        print(f"[*] Abriendo en ventana de aplicación nativa ({os.path.basename(ejecutable)} --app)...")
        try:
            subprocess.Popen([
                ejecutable,
                f"--app={url}",
                "--window-size=1280,840",
                "--app-id=colombia-radar",
            ])
            return
        except Exception as e:
            print(f"[!] No se pudo iniciar el modo app: {e}")

    # 2. Fallback estándar
    print("[*] Abriendo en el navegador predeterminado...")
    webbrowser.open(url)


def main():
    host = "127.0.0.1"
    port = 5000
    url = f"http://{host}:{port}"

    print("==================================================")
    print("      COLOMBIA RADAR - APLICACIÓN PARA PC         ")
    print("==================================================")
    print(f"[*] Servidor backend activo en: {url}")

    # Verificar si está disponible pywebview para ventana 100% nativa
    try:
        import webview
        print("[*] Motor 'pywebview' detectado. Iniciando ventana nativa de escritorio...")

        # Iniciar Flask en hilo separado
        t_flask = threading.Thread(target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False))
        t_flask.daemon = True
        t_flask.start()

        # Esperar 0.5s a que Flask responda
        time.sleep(0.5)

        # Crear y arrancar la ventana de escritorio
        webview.create_window(
            title="Colombia Radar - Inteligencia de Mercado",
            url=url,
            width=1280,
            height=850,
            resizable=True,
            min_size=(900, 600),
        )
        webview.start()
        sys.exit(0)

    except ImportError:
        # Si no tiene pywebview instalado, usamos el lanzador de ventana de app
        pass

    # Iniciar hilo para abrir la ventana de app
    t_ui = threading.Thread(target=abrir_ventana_escritorio, args=(url,))
    t_ui.daemon = True
    t_ui.start()

    # Ejecutar servidor Flask en el hilo principal
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
