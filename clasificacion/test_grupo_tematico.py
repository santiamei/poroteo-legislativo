"""Tests de grupo_tematico.py.

Los casos reales usan los títulos tal cual aparecen en
data/processed/votos_consolidado.csv para las 13 actas con eje asignado
a mano (ejes_manuales.yaml) -- el clasificador se valida contra la
realidad, no contra ejemplos inventados.
"""

import re

from clasificacion.grupo_tematico import GRUPO_GENERAL, GRUPOS_VALIDOS, elegir_grupo, ejes_del_grupo


def test_grupos_validos_son_los_tres_esperados():
    assert set(GRUPOS_VALIDOS) == {"economico", "regulacion_produccion", "institucional_derechos"}


def test_ejes_del_grupo_economico():
    assert ejes_del_grupo("economico") == ["Económico/fiscal"]


def test_ejes_del_grupo_regulacion_produccion():
    assert ejes_del_grupo("regulacion_produccion") == ["Laboral", "Ambiental/regulatorio", "Comercio exterior"]


def test_ejes_del_grupo_institucional_derechos():
    assert ejes_del_grupo("institucional_derechos") == ["Social/derechos", "Federal/servicios"]


def test_ejes_de_grupo_inexistente_devuelve_vacio():
    assert ejes_del_grupo("no_existe") == []


# ---------------------------------------------------------------------------
# casos reales, títulos tal cual salen de votos_consolidado.csv
# ---------------------------------------------------------------------------


def test_od_1_presupuesto_cae_en_economico():
    r = elegir_grupo("O.D. 1 - PRESUPUESTO GENERAL DE LA ADM. NACIONAL PARA EL E.F. CORRESP. AL AÑO 2026. DICT. DE MAY. VOT. EN GRAL.")
    assert r.grupo == "economico"
    assert r.confianza == "alta"


def test_od_3_inocencia_fiscal_cae_en_economico():
    r = elegir_grupo("O.D. 3 - LEY DE INOCENCIA FISCAL. DICT. DE MAY. VOT. EN GRAL.")
    assert r.grupo == "economico"


def test_od_149_super_rigi_cae_en_economico():
    r = elegir_grupo('O.D. 149 - RÉGIMEN DE INCENTIVO PARA GRANDES INVERSIONES EN NUEVAS INDUSTRIAS, "SÚPER RIGI". CREACIÓN. DICT. DE MAY. VOT. EN GRAL.')
    assert r.grupo == "economico"


def test_od_211_bcra_cae_en_economico():
    r = elegir_grupo("O.D. 211 -  CARTA ORGÁNICA DEL BCRA. MODIFICACIÓN. DICT. DE MAY. VOT. EN GRAL.")
    assert r.grupo == "economico"


def test_od_209_ganancias_cae_en_economico():
    r = elegir_grupo("O.D. 209 - LEYES 11.683 Y 27.799 RELATIVAS A LA MOD. SIMPL. DE DECL. JURADA DEL IMP. A LAS GANANCIAS. MODIF. DICT. DE MAY. VOT. EN GRAL.")
    assert r.grupo == "economico"


def test_od_148_conciliacion_acreedores_cae_en_economico():
    # título abreviado real: "ACREED." en vez de "ACREEDORES"
    r = elegir_grupo("O.D. 148 - AC. DE CONCILIACIÓN E/ LA REP. ARG. Y BAINBRIDGE LTD. Y E/ LA REP. ARG. Y EL GRUPO DE ACREED. ENCABEZADO POR ATTESTOR VMF. VOT GRAL Y PART.")
    assert r.grupo == "economico"


def test_od_6_modernizacion_laboral_cae_en_regulacion_produccion():
    r = elegir_grupo("O.D. 6 - LEY DE MODERNIZACIÓN LABORAL. DICT. DE MAY. VOT. EN GRAL.")
    assert r.grupo == "regulacion_produccion"


def test_od_7_glaciares_cae_en_regulacion_produccion():
    r = elegir_grupo("O.D. 7 - LEY 26.639, DE RÉGIMEN DE PRESUP. MÍN. PARA LA PRESERV. DE LOS GLACIARES Y DEL AMB. PERIGLACIAL. MODIF. DICT. DE MAY. VOT. EN GRAL. Y PART.")
    assert r.grupo == "regulacion_produccion"


def test_od_5_mercosur_ue_cae_en_regulacion_produccion():
    r = elegir_grupo("O.D. 5 - ACUERDO MERCOSUR - UNIÓN EUROPEA. VOT. EN GRAL. Y PART.")
    assert r.grupo == "regulacion_produccion"


def test_od_85_patentes_cae_en_regulacion_produccion():
    r = elegir_grupo("O.D. 85 - TRATADO DE COOP. EN MATERIA DE PATENTES SUSCRIPTO EN WASHINGTON -EEUU DE AMÉRICA-. APROBACIÓN. DICT. DE MAYORÍA. VOT. EN GRAL. Y PART.")
    assert r.grupo == "regulacion_produccion"


def test_od_4_penal_juvenil_cae_en_institucional_derechos():
    r = elegir_grupo("O.D. 4 - RÉGIMEN PENAL JUVENIL. ESTABLECIMIENTO. DICT. DE MAY. VOT. EN GRAL.")
    assert r.grupo == "institucional_derechos"


def test_od_84_zona_fria_cae_en_institucional_derechos():
    r = elegir_grupo("O.D. 84 - RÉGIMEN DE ZONA FRÍA. MODIFICACIÓN. DICT. DE MAY. VOT. EN GRAL.")
    assert r.grupo == "institucional_derechos"


# ---------------------------------------------------------------------------
# red de seguridad: títulos reales sin vocabulario de ninguno de los 3 grupos
# ---------------------------------------------------------------------------


def test_tratado_extradicion_cae_en_red_de_seguridad():
    r = elegir_grupo("O.D. 16 - TRATADO DE EXTRADICIÓN ENTRE LA REP. ARGENTINA Y LA REP. DE POLONIA. APROBACIÓN. VOT. EN GRAL. Y PART.")
    assert r.grupo is GRUPO_GENERAL
    assert r.confianza == "red_de_seguridad"


def test_declaracion_ceremonial_cae_en_red_de_seguridad():
    # títulos declarativos ("capital nacional de...") no deben matchear
    # por palabras genéricas como EDUCACION/PROVINCIA -- justamente por
    # eso esas palabras no están en patrones_grupo_tematico.yaml.
    r = elegir_grupo("O.D. 248 - PROVINCIA DE SAN JUAN, CUNA DE DOMINGO FAUSTINO SARMIENTO Y CAPITAL NACIONAL DE LA EDUCACIÓN.")
    assert r.grupo is GRUPO_GENERAL


def test_reorganizacion_judicial_federal_no_matchea_institucional_derechos():
    # "FEDERAL" aparece acá por "Cámara Federal de Apelaciones", nada que
    # ver con el eje Federal/servicios -- por eso "FEDERAL" solo no es
    # palabra clave de institucional_derechos.
    r = elegir_grupo("O.D. 263 - CÁMARA FEDERAL DE APELACIONES DE TUCUMÁN. REORGANIZACIÓN. VOT. EN GRAL. Y PART.")
    assert r.grupo is GRUPO_GENERAL


def test_titulo_vacio_cae_en_red_de_seguridad():
    r = elegir_grupo("")
    assert r.grupo is GRUPO_GENERAL
    assert r.confianza == "red_de_seguridad"


def test_titulo_none_no_rompe():
    r = elegir_grupo(None)
    assert r.grupo is GRUPO_GENERAL


def test_senal_ambigua_entre_grupos_cae_en_red_de_seguridad():
    # un título que matchea UNA palabra de cada uno de dos grupos distintos
    # (empate) debe caer en la red de seguridad, no elegir uno arbitrario.
    patrones = {
        "economico": [re.compile("FISCAL")],
        "regulacion_produccion": [re.compile("LABORAL")],
    }
    r = elegir_grupo("RÉGIMEN FISCAL Y LABORAL COMBINADO", patrones=patrones)
    assert r.grupo is GRUPO_GENERAL
    assert r.confianza == "red_de_seguridad"
