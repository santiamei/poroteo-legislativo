"""Verifica que RepositorioEvidencia.desde_artefacto() reproduzca
EXACTAMENTE lo mismo que el pipeline completo (RepositorioEvidencia()
leyendo los CSV/JSON crudos) — el round-trip de serialización no puede
cambiar ni una probabilidad, o la app estaría prediciendo otra cosa que
lo validado contra la OD 209.

Requiere modelo/artefacto_evidencia.json ya generado (generar_artefacto.py).
"""

import pytest

from modelo.datos_evidencia import ARTEFACTO_PATH_DEFAULT, RepositorioEvidencia
from modelo.interfaz import Votacion
from modelo.promedios import ModeloPromedios

pytestmark = pytest.mark.skipif(
    not ARTEFACTO_PATH_DEFAULT.exists(), reason="correr generar_artefacto.py primero"
)


@pytest.fixture(scope="module")
def evidencia_cruda():
    return RepositorioEvidencia()


@pytest.fixture(scope="module")
def evidencia_artefacto():
    return RepositorioEvidencia.desde_artefacto()


def test_universo_identico(evidencia_cruda, evidencia_artefacto):
    assert evidencia_artefacto.universo_diputados() == evidencia_cruda.universo_diputados()


def test_ejes_disponibles_identicos(evidencia_cruda, evidencia_artefacto):
    assert evidencia_artefacto.ejes_disponibles() == evidencia_cruda.ejes_disponibles()
    assert evidencia_artefacto.n_actas_por_eje() == evidencia_cruda.n_actas_por_eje()


def test_cohesion_identica(evidencia_cruda, evidencia_artefacto):
    bloques = {evidencia_cruda.bloque_actual_de(i) for i in evidencia_cruda.universo_diputados()}
    for bloque in bloques:
        assert evidencia_artefacto.cohesion_de_bloque(bloque) == evidencia_cruda.cohesion_de_bloque(bloque)


@pytest.mark.parametrize("eje", [None, "Económico/fiscal", "Comercio exterior"])
def test_predicciones_sin_od_identicas(evidencia_cruda, evidencia_artefacto, eje):
    modelo_crudo = ModeloPromedios(evidencia_cruda)
    modelo_artefacto = ModeloPromedios(evidencia_artefacto)

    votacion = Votacion(titulo="comparación", eje=eje)
    pred_crudo = modelo_crudo.predecir(votacion)
    pred_artefacto = modelo_artefacto.predecir(votacion)

    assert set(pred_crudo) == set(pred_artefacto)
    for id_ in pred_crudo:
        a, b = pred_crudo[id_], pred_artefacto[id_]
        assert a.probabilidad_afirmativo == pytest.approx(b.probabilidad_afirmativo)
        assert a.banda_confianza == pytest.approx(b.banda_confianza)
        assert a.n_evidencia_efectiva == pytest.approx(b.n_evidencia_efectiva)
        assert a.fuente_dominante == b.fuente_dominante
