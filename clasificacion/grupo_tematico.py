#!/usr/bin/env python3
"""Selección automática y OCULTA del grupo temático que apoya la
proyección de una OD, a partir de su título.

Etapa 2 del rediseño: el usuario NUNCA elige ni ve el eje/grupo — este
módulo lo decide internamente, con una red de seguridad explícita (ver
GRUPO_GENERAL) para no forzar nunca una categoría dudosa. El resultado
queda expuesto en SeleccionGrupo para poder auditar la decisión (logs,
tests), pero la UI no lo muestra.

Dos archivos de configuración, separados a propósito:
  grupos_tematicos.yaml         — grupo -> lista de ejes finos que agrupa.
  patrones_grupo_tematico.yaml  — grupo -> palabras clave para matchear
                                   contra el título de la OD.
Reagrupar ejes o ajustar palabras clave es editar YAML, no tocar código.

Reutiliza clasificador.normalizar() (mayúsculas, sin acentos, puntos a
espacio) en vez de reimplementar la normalización de títulos sucios.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .clasificador import normalizar

GRUPOS_PATH = Path(__file__).parent / "grupos_tematicos.yaml"
PATRONES_GRUPO_PATH = Path(__file__).parent / "patrones_grupo_tematico.yaml"

# Red de seguridad: ningún grupo con confianza suficiente -> se usa la
# evidencia general (todas las actas de fondo), nunca se fuerza una
# categoría dudosa ni se rompe la proyección.
GRUPO_GENERAL = None


@dataclass(frozen=True)
class SeleccionGrupo:
    """Resultado de clasificar el título de una OD. Pensado para loguearse
    y auditarse (quién eligió qué y con qué evidencia) — NO para mostrarse
    en la UI."""

    grupo: Optional[str]           # None = red de seguridad (evidencia general)
    confianza: str                 # "alta" | "red_de_seguridad"
    palabras_matcheadas: tuple     # patrones que dispararon la elección, para auditoría
    titulo_normalizado: str


def _cargar_grupos(path=GRUPOS_PATH) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {grupo: list((info or {}).get("ejes", [])) for grupo, info in data.items()}


def _cargar_patrones_grupo(path=PATRONES_GRUPO_PATH) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        grupo: [re.compile(p, re.IGNORECASE) for p in (patrones or [])]
        for grupo, patrones in data.items()
    }


_GRUPOS_A_EJES = _cargar_grupos()
_PATRONES_POR_GRUPO = _cargar_patrones_grupo()

GRUPOS_VALIDOS = tuple(_GRUPOS_A_EJES.keys())


def ejes_del_grupo(grupo: str) -> list:
    """Los ejes finos que agrupa `grupo` (según grupos_tematicos.yaml)."""
    return list(_GRUPOS_A_EJES.get(grupo, []))


def elegir_grupo(titulo: str, patrones=None) -> SeleccionGrupo:
    """Clasifica un título de OD a un grupo temático, o a la red de
    seguridad (GRUPO_GENERAL) si no hay una señal clara.

    `patrones`: permite inyectar un set de patrones distinto al de
    patrones_grupo_tematico.yaml (útil para tests).

    Regla de desempate: si dos o más grupos matchean la MISMA cantidad
    (máxima) de palabras clave, se considera ambiguo y se cae a la red de
    seguridad en vez de elegir uno arbitrariamente.
    """
    patrones = patrones if patrones is not None else _PATRONES_POR_GRUPO
    texto = normalizar(titulo)
    if not texto:
        return SeleccionGrupo(GRUPO_GENERAL, "red_de_seguridad", (), texto)

    hits_por_grupo = {}
    for grupo, lista_patrones in patrones.items():
        hits = tuple(p.pattern for p in lista_patrones if p.search(texto))
        if hits:
            hits_por_grupo[grupo] = hits

    if not hits_por_grupo:
        return SeleccionGrupo(GRUPO_GENERAL, "red_de_seguridad", (), texto)

    maximo = max(len(hits) for hits in hits_por_grupo.values())
    ganadores = [g for g, hits in hits_por_grupo.items() if len(hits) == maximo]
    if len(ganadores) > 1:
        # señal ambigua entre grupos -> mejor no forzar ninguno
        return SeleccionGrupo(GRUPO_GENERAL, "red_de_seguridad", (), texto)

    grupo_elegido = ganadores[0]
    return SeleccionGrupo(grupo_elegido, "alta", hits_por_grupo[grupo_elegido], texto)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Uso: python -m clasificacion.grupo_tematico 'titulo de la OD'")
        sys.exit(1)

    resultado = elegir_grupo(sys.argv[1])
    print(f"grupo: {resultado.grupo!r} (confianza: {resultado.confianza})")
    print(f"palabras_matcheadas: {resultado.palabras_matcheadas}")
    print(f"titulo_normalizado: {resultado.titulo_normalizado}")
