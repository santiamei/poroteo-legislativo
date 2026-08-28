#!/usr/bin/env python3
"""Clasificación de títulos de votación por categoría de fondo/forma.

Módulo independiente: no hace requests de red ni depende de otros módulos
del proyecto. Toma un título de acta (texto sucio, con abreviaturas y
puntuación inconsistente) y lo clasifica en una de cuatro categorías:

  PROCEDIMIENTO   — mociones/trámites de procedimiento parlamentario
                     (sobre tablas, cuarto intermedio, preferencia, etc.)
  FONDO_GENERAL   — votación en general de un proyecto
  FONDO_PARTICULAR — votación en particular (por artículo) de un proyecto
  REVISAR         — no matcheó ningún patrón conocido; requiere revisión
                     manual antes de usarse en el pipeline.

Los patrones están en patrones.yaml, al lado de este archivo, para poder
ajustarlos sin tocar código a medida que se validan contra títulos reales.

Dentro de PROCEDIMIENTO, algunos patrones traen además una etiqueta de
subcategoría (por ahora, APARTAMIENTO, para apartamiento del reglamento)
que queda expuesta en Clasificacion.etiqueta. La etiqueta NO es una
categoría aparte -sigue siendo PROCEDIMIENTO, fuera del modelo de fondo-
pero permite aislar después ese tipo de votación como señal política
propia (quién acompaña habilitar tratar un tema sensible, más allá de si
después acompaña el fondo).

Uso:
    from clasificacion.clasificador import clasificar_votacion
    resultado = clasificar_votacion('O.D. 207 - ... VOT. EN GRAL. Y PART.')
    resultado.categoria         # 'FONDO_GENERAL'
    resultado.etiqueta          # None (solo se usa dentro de PROCEDIMIENTO por ahora)
    resultado.patron_matcheado  # el regex que matcheó, para auditoría
"""

import re
import unicodedata
from pathlib import Path
from typing import NamedTuple, Optional

import yaml

PATRONES_PATH = Path(__file__).parent / "patrones.yaml"

# Prioridad de evaluación: la primera categoría de esta lista cuyo patrón
# matchee gana, sin importar si una categoría posterior también matchearía.
ORDEN_PRIORIDAD = ["PROCEDIMIENTO", "FONDO_GENERAL", "FONDO_PARTICULAR"]

REVISAR = "REVISAR"


class Clasificacion(NamedTuple):
    categoria: str
    etiqueta: Optional[str]  # subcategoría dentro de la categoría (ej. APARTAMIENTO); None si no aplica
    patron_matcheado: Optional[str]  # el regex que matcheó; None si categoria == REVISAR
    texto_normalizado: str


def normalizar(titulo):
    """Mayúsculas, sin acentos, puntos unificados a espacio, espacios
    colapsados. Deja el texto listo para matchear patrones sobre títulos
    sucios/abreviados sin importar cómo esté puntuado el original."""
    if not titulo:
        return ""
    texto = titulo.upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace(".", " ")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _cargar_patrones(path=PATRONES_PATH):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    compilados = {}
    for categoria, patrones in data.items():
        if categoria == REVISAR:
            continue
        entradas = []
        for item in patrones or []:
            # cada entrada es un string simple, o un dict {patron, etiqueta}
            # cuando el patrón amerita una subcategoría dentro de esta categoría.
            if isinstance(item, dict):
                patron_str, etiqueta = item["patron"], item.get("etiqueta")
            else:
                patron_str, etiqueta = item, None
            entradas.append((patron_str, re.compile(patron_str), etiqueta))
        compilados[categoria] = entradas
    return compilados


_PATRONES_POR_DEFECTO = _cargar_patrones()


def clasificar_votacion(titulo, patrones=None):
    """Clasifica un título de votación. `patrones` permite inyectar un set
    de patrones distinto al de patrones.yaml (útil para tests)."""
    patrones = patrones if patrones is not None else _PATRONES_POR_DEFECTO
    texto = normalizar(titulo)

    for categoria in ORDEN_PRIORIDAD:
        for patron_str, patron_re, etiqueta in patrones.get(categoria, []):
            if patron_re.search(texto):
                return Clasificacion(categoria, etiqueta, patron_str, texto)

    return Clasificacion(REVISAR, None, None, texto)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Uso: python clasificacion/clasificador.py 'titulo de la votacion'")
        sys.exit(1)

    resultado = clasificar_votacion(sys.argv[1])
    print(f"categoria: {resultado.categoria}")
    print(f"etiqueta: {resultado.etiqueta}")
    print(f"patron_matcheado: {resultado.patron_matcheado}")
    print(f"texto_normalizado: {resultado.texto_normalizado}")
