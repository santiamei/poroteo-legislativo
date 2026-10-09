"""Tests de seleccion_tema.py.

Usa RepositorioEvidencia() real (no el artefacto) porque lo que se
valida acá es justamente que n_actas_por_grupo()/n_actas_generales()
coincidan con lo que calcula el pipeline completo. test_artefacto.py ya
cubre que el artefacto reproduce lo mismo.
"""

import pytest

from clasificacion.grupo_tematico import GRUPO_GENERAL
from modelo.datos_evidencia import RepositorioEvidencia
from modelo.seleccion_tema import seleccionar_tema_para_od


@pytest.fixture(scope="module")
def evidencia():
    return RepositorioEvidencia()


def test_od_209_ganancias_cae_en_economico(evidencia):
    titulo = (
        "LEYES 11.683 Y 27.799 RELATIVAS A LA MOD. SIMPL. DE DECL. "
        "JURADA DEL IMP. A LAS GANANCIAS. MODIF. DICT. DE MAY. VOT. EN GRAL."
    )
    r = seleccionar_tema_para_od(titulo, evidencia)
    assert r.seleccion.grupo == "economico"
    assert r.seleccion.confianza == "alta"
    assert r.eje_para_modelo == "economico"
    assert r.n_actas == evidencia.n_actas_por_grupo()["economico"]
    assert r.n_actas > 0


def test_titulo_laboral_cae_en_regulacion_produccion(evidencia):
    r = seleccionar_tema_para_od("LEY DE MODERNIZACIÓN LABORAL. DICT. DE MAY. VOT. EN GRAL.", evidencia)
    assert r.seleccion.grupo == "regulacion_produccion"
    assert r.eje_para_modelo == "regulacion_produccion"


def test_titulo_penal_juvenil_cae_en_institucional_derechos(evidencia):
    r = seleccionar_tema_para_od("RÉGIMEN PENAL JUVENIL. ESTABLECIMIENTO. DICT. DE MAY. VOT. EN GRAL.", evidencia)
    assert r.seleccion.grupo == "institucional_derechos"
    assert r.eje_para_modelo == "institucional_derechos"


def test_titulo_sin_senal_tematica_cae_en_red_de_seguridad(evidencia):
    # tratado de extradición: no tiene vocabulario de ninguno de los 3 grupos
    titulo = "TRATADO DE EXTRADICIÓN ENTRE LA REP. ARGENTINA Y LA REP. DE POLONIA. APROBACIÓN."
    r = seleccionar_tema_para_od(titulo, evidencia)
    assert r.seleccion.grupo is GRUPO_GENERAL
    assert r.seleccion.confianza == "red_de_seguridad"
    assert r.eje_para_modelo is None  # None ya significa "evidencia general" en todo el modelo
    assert r.n_actas == evidencia.n_actas_generales()
    assert r.n_actas > 0  # la red de seguridad nunca deja sin evidencia


def test_titulo_vacio_cae_en_red_de_seguridad_sin_romper(evidencia):
    r = seleccionar_tema_para_od("", evidencia)
    assert r.seleccion.grupo is GRUPO_GENERAL
    assert r.eje_para_modelo is None
    assert r.n_actas == evidencia.n_actas_generales()


def test_eje_para_modelo_funciona_con_tasa_individual(evidencia):
    # el punto del diseño: eje_para_modelo es un string usable directo en
    # tasa_*(eje=...), sin ningún caso especial para grupo vs. eje fino.
    r = seleccionar_tema_para_od("RÉGIMEN DE INCENTIVO PARA GRANDES INVERSIONES. SÚPER RIGI.", evidencia)
    assert r.eje_para_modelo == "economico"
    tasa = evidencia.tasa_individual("petri-luis", eje=r.eje_para_modelo)
    assert tasa.n > 0
