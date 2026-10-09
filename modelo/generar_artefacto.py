#!/usr/bin/env python3
"""Genera modelo/artefacto_evidencia.json: el estado agregado de
RepositorioEvidencia, serializado liviano, para que app.py lo cargue sin
tocar data/raw ni data/processed (que no existen en el deploy).

Corre UNA VEZ, local, cada vez que cambie algo en la capa de ingesta
(nueva acta, bloque renormalizado, etc.) — nunca se ejecuta en la app.

Uso:
    python modelo/generar_artefacto.py
"""

from datos_evidencia import ARTEFACTO_PATH_DEFAULT, RepositorioEvidencia


def main():
    print("Cargando evidencia desde el pipeline completo (CSV/JSON crudos)...")
    evidencia = RepositorioEvidencia()

    print(f"Diputados en el universo (artefacto): {len(evidencia.universo_diputados())}")
    print(f"Ejes disponibles: {evidencia.ejes_disponibles()}")
    print(f"Actas por eje: {evidencia.n_actas_por_eje()}")

    ruta = evidencia.exportar_artefacto(ARTEFACTO_PATH_DEFAULT)
    tamano_kb = ruta.stat().st_size / 1024
    print(f"\nArtefacto guardado en: {ruta} ({tamano_kb:.1f} KB)")


if __name__ == "__main__":
    main()
