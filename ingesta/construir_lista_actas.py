#!/usr/bin/env python3
"""Construye la lista de actas de diputados a descargar (ingesta/actas_a_descargar.json)
a partir de páginas de actas-search de Data CP, ya obtenidas manualmente
(pegadas en el navegador y copiadas a archivos JSON locales, porque
/api/ está deshabilitado por robots.txt y no lo llamamos programáticamente).

Este script NO hace requests de red. Toma archivos JSON con la forma
{"total": N, "page": N, "limit": N, "actas": [...]} — el mismo shape que
devuelve /api/congreso/actas-search — y:

  1. Junta todos los objetos "acta" de todas las páginas dadas.
  2. Filtra camara == "diputados" (por si el listado original traía
     senadores mezclados).
  3. Dedupea por actaId (puede haber solapamiento entre páginas).
  4. Filtra fecha >= FECHA_DESDE (DD/MM/YYYY, parseado como día/mes/año).
  5. Se queda solo con actaId, titulo, fecha, resultado — descarta los
     campos de conteo agregado (afirmativos/negativos/abstenciones/
     ausentes), que ya confirmamos rotos en el reconocimiento de Data CP;
     los votos reales se recalculan después desde el detalle de cada acta.
  6. Ordena por fecha ascendente y guarda en ingesta/actas_a_descargar.json.

Uso:
    python ingesta/construir_lista_actas.py <archivo1.json> [archivo2.json ...]
"""

import json
import sys
from datetime import datetime
from pathlib import Path

FECHA_DESDE = datetime(2025, 12, 10)
OUTPUT_PATH = Path(__file__).parent / "actas_a_descargar.json"


def parsear_fecha(fecha_str):
    """fecha viene como texto DD/MM/YYYY."""
    return datetime.strptime(fecha_str, "%d/%m/%Y")


def cargar_actas(paths):
    todas = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        todas.extend(data["actas"])
    return todas


def construir_lista(actas_crudas):
    solo_diputados = [a for a in actas_crudas if a["camara"] == "diputados"]

    deduplicadas = {}
    for acta in solo_diputados:
        deduplicadas[acta["actaId"]] = acta  # última ocurrencia gana; son iguales entre páginas

    en_ventana = [
        acta for acta in deduplicadas.values()
        if parsear_fecha(acta["fecha"]) >= FECHA_DESDE
    ]

    reducidas = [
        {
            "actaId": acta["actaId"],
            "titulo": acta["titulo"],
            "fecha": acta["fecha"],
            "resultado": acta["resultado"],
        }
        for acta in en_ventana
    ]

    reducidas.sort(key=lambda a: parsear_fecha(a["fecha"]))
    return reducidas, len(actas_crudas), len(solo_diputados)


def main():
    if len(sys.argv) < 2:
        print("Uso: python ingesta/construir_lista_actas.py <archivo1.json> [archivo2.json ...]")
        sys.exit(1)

    actas_crudas = cargar_actas(sys.argv[1:])
    lista_final, total_crudo, total_diputados = construir_lista(actas_crudas)

    OUTPUT_PATH.write_text(
        json.dumps(lista_final, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    por_anio = {}
    for acta in lista_final:
        anio = parsear_fecha(acta["fecha"]).year
        por_anio[anio] = por_anio.get(anio, 0) + 1

    print(f"Registros crudos leídos (todas las páginas, todas las cámaras): {total_crudo}")
    print(f"Después de filtrar camara == 'diputados': {total_diputados}")
    print(f"Actas de diputados con fecha >= {FECHA_DESDE.strftime('%d/%m/%Y')}: {len(lista_final)}")
    for anio, n in sorted(por_anio.items()):
        print(f"  {anio}: {n}")
    if lista_final:
        print(f"Rango de fechas: {lista_final[0]['fecha']} -> {lista_final[-1]['fecha']}")
    print(f"\nGuardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
