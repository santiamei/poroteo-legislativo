#!/usr/bin/env python3
"""Selección del universo de evidencia histórica que apoya la proyección
de una OD — Etapa 2 del rediseño de la app.

Puente entre clasificacion.grupo_tematico (clasifica un título a un
grupo temático, SIN depender de nada del modelo) y RepositorioEvidencia
(sabe cuántas actas tiene cada grupo). El usuario nunca ve ni elige nada
de esto: `eje_para_modelo` es directamente lo que se le pasa a
Votacion(eje=...) — y si la clasificación cae en la red de seguridad,
`eje_para_modelo` es None, que YA significa "evidencia general" en todo
el resto del modelo (ver promedios.py: `if eje:` es falsy), así que no
hace falta ningún caso especial para la red de seguridad en el modelo.

NO se usa todavía desde app.py/poroteo.py -- esta etapa es solo la
lógica de selección, para integrarse en la UI en una etapa posterior.
"""

from dataclasses import dataclass
from typing import Optional

from clasificacion.grupo_tematico import GRUPO_GENERAL, SeleccionGrupo, elegir_grupo

from .datos_evidencia import RepositorioEvidencia


@dataclass(frozen=True)
class ResultadoSeleccionTema:
    """Pensado para auditoría/logging (quién eligió qué grupo y con
    cuánta evidencia) -- NUNCA para mostrarse en la UI."""

    seleccion: SeleccionGrupo       # grupo, confianza, palabras que matchearon
    eje_para_modelo: Optional[str]  # listo para Votacion(eje=...) / tasa_*(eje=...)
    n_actas: int                    # tamaño de la evidencia que se va a usar


def seleccionar_tema_para_od(titulo: str, evidencia: RepositorioEvidencia) -> ResultadoSeleccionTema:
    """Clasifica el título de una OD a un grupo temático y resuelve
    cuántas actas históricas respaldan esa elección. Si la clasificación
    cae en la red de seguridad (GRUPO_GENERAL), usa toda la evidencia de
    fondo general en vez de forzar una categoría dudosa -- nunca rompe ni
    deja a una OD sin proyección."""
    seleccion = elegir_grupo(titulo)
    if seleccion.grupo is GRUPO_GENERAL:
        return ResultadoSeleccionTema(seleccion, None, evidencia.n_actas_generales())

    n_actas = evidencia.n_actas_por_grupo().get(seleccion.grupo, 0)
    return ResultadoSeleccionTema(seleccion, seleccion.grupo, n_actas)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Uso: python -m modelo.seleccion_tema 'titulo de la OD'")
        sys.exit(1)

    ev = RepositorioEvidencia()
    r = seleccionar_tema_para_od(sys.argv[1], ev)
    print(f"grupo elegido: {r.seleccion.grupo!r} (confianza: {r.seleccion.confianza})")
    print(f"palabras_matcheadas: {r.seleccion.palabras_matcheadas}")
    print(f"eje_para_modelo: {r.eje_para_modelo!r}")
    print(f"n_actas: {r.n_actas}")
