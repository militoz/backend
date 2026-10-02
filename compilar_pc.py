#!/usr/bin/env python3
"""
Script para compilar Colombia Radar como ejecutable autónomo para PC (.exe en Windows, binario en Linux/Mac).
Utiliza PyInstaller para empaquetar Python, Flask, dependencias, plantillas y archivos YAML en un solo archivo.
"""
import sys
import os
import platform
import subprocess

def compilar():
    sistema = platform.system().lower()
    sep = ";" if sistema == "windows" else ":"

    print("==================================================")
    print("      COMPILADOR DE COLOMBIA RADAR PARA PC        ")
    print("==================================================")

    # Verificar si PyInstaller está instalado
    try:
        import PyInstaller
    except ImportError:
        print("[*] Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Carpetas a incluir dentro del ejecutable
    datos = [
        f"templates{sep}templates",
        f"config{sep}config",
        f"static{sep}static",
    ]

    comando = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=ColombiaRadar",
        "--onefile",
        # Ocultar la consola de comandos en la versión final de escritorio:
        # "--noconsole",
        "--clean",
        "--add-data", datos[0],
        "--add-data", datos[1],
        "--add-data", datos[2],
        "--hidden-import=radar",
        "--hidden-import=radar.server",
        "--hidden-import=radar.collectors",
        "--hidden-import=radar.analysis",
        "--hidden-import=yaml",
        "--hidden-import=bs4",
        "--hidden-import=flask",
        "--hidden-import=jinja2",
        "lanzador.py",
    ]

    print("[*] Ejecutando compilación con comando:")
    print(" ".join(comando))

    resultado = subprocess.run(comando)
    if resultado.returncode == 0:
        print("\n==================================================")
        print("[+] ¡COMPILACIÓN EXITOSA!")
        if sistema == "windows":
            print("[+] Tu ejecutable está listo en: dist/ColombiaRadar.exe")
        else:
            print("[+] Tu ejecutable está listo en: dist/ColombiaRadar")
        print("==================================================")
    else:
        print("[!] Error durante la compilación.")

if __name__ == "__main__":
    compilar()
