#!/usr/bin/env python3
"""Repositorio de evidencia histórica: individual / subgrupo / bloque.

Separado del modelo a propósito: ModeloPromedios y el futuro
ModeloBayesiano (PyMC) consumen la MISMA evidencia sin duplicar la carga
de datos. Este módulo solo lee y expone tasas — no pondera ni combina
nada, eso es responsabilidad del modelo (promedios.py).

Fuentes:
    - data/processed/votos_consolidado.csv                (histórico voto x acta x diputado)
    - ingesta/tabla_maestra_diputados.json                 (identidad, nombre canónico)
    - ingesta/mapeo_bloques_diputados.json                 (bloque canónico por fecha)
    - data/processed/cohesion_bloques_fondo_general.csv    (Rice por bloque, sobre las 42)
    - data/processed/clusters_conflicto_13actas.csv        (subgrupo, corte de 8 clusters)
    - clasificacion/ejes_manuales.yaml                     (eje por acta, solo las 13 disputadas)

"Posición válida" para calcular tasas = AFIRMATIVO, NEGATIVO o ABSTENCION
(misma definición usada en toda la etapa de matriz/cohesión/división —
excluye AUSENTE, PRESIDENTE y banca vacante).

Universo de predicción: diputados cuyo ÚLTIMO período de bloque conocido
llega hasta la última acta de la ventana (27/08/2026) — proxy de "sigue
en banca". Excluye a quienes ya fueron reemplazados (ej. Pitrola, Ravier).
"""

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "processed"
INGESTA_DIR = BASE_DIR / "ingesta"
CLASIFICACION_DIR = BASE_DIR / "clasificacion"

VOTOS_PATH = DATA_DIR / "votos_consolidado.csv"
TABLA_MAESTRA_PATH = INGESTA_DIR / "tabla_maestra_diputados.json"
MAPEO_BLOQUES_PATH = INGESTA_DIR / "mapeo_bloques_diputados.json"
COHESION_PATH = DATA_DIR / "cohesion_bloques_fondo_general.csv"
CLUSTERS_PATH = DATA_DIR / "clusters_conflicto_13actas.csv"
EJES_PATH = CLASIFICACION_DIR / "ejes_manuales.yaml"

CORTE_SUBGRUPO_K = 8  # confirmado con el usuario
POSICIONES_VALIDAS = {"AFIRMATIVO", "NEGATIVO", "ABSTENCION"}
FECHA_FIN_VENTANA = "27/08/2026"


@dataclass(frozen=True)
class TasaEvidencia:
    """Una tasa histórica de AFIRMATIVO con su tamaño de muestra."""

    probabilidad_afirmativo: float
    n: int


def _parsear_fecha(s: str) -> datetime:
    return datetime.strptime(s, "%d/%m/%Y")


class RepositorioEvidencia:
    """Carga toda la evidencia una sola vez y expone consultas simples.
    No pondera nada — cada método devuelve la tasa CRUDA a ese nivel."""

    def __init__(self):
        self._nombres = self._cargar_nombres()
        self._bloque_actual, self._universo = self._cargar_bloque_actual_y_universo()
        self._subgrupo = self._cargar_subgrupo()
        self._cohesion = self._cargar_cohesion()
        self._ejes_por_acta = self._cargar_ejes()

        # agregados[nivel][clave][eje_o_None] = [n, afirmativos]
        self._agg_individual = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        self._agg_subgrupo = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        self._agg_bloque = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        self._cargar_y_agregar_votos()

    # ------------------------------------------------------------------
    # carga
    # ------------------------------------------------------------------

    def _cargar_nombres(self):
        tabla = json.loads(TABLA_MAESTRA_PATH.read_text(encoding="utf-8"))
        return {p["id"]: p["nombre_canonico"] for p in tabla}

    def _cargar_bloque_actual_y_universo(self):
        mapeo = json.loads(MAPEO_BLOQUES_PATH.read_text(encoding="utf-8"))
        bloque_actual = {}
        universo = []
        for id_, periodos in mapeo.items():
            if not periodos:
                continue
            ultimo = periodos[-1]
            bloque_actual[id_] = ultimo["bloque_canonico"]
            if ultimo["hasta_fecha"] == FECHA_FIN_VENTANA:
                universo.append(id_)
        return bloque_actual, sorted(universo)

    def _cargar_subgrupo(self):
        subgrupo = {}
        with open(CLUSTERS_PATH, encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                if int(fila["k_clusters"]) == CORTE_SUBGRUPO_K:
                    subgrupo[fila["id_diputado"]] = int(fila["cluster"])
        return subgrupo

    def _cargar_cohesion(self):
        cohesion = {}
        with open(COHESION_PATH, encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                valor = fila["cohesion_rice_promedio"]
                cohesion[fila["bloque"]] = float(valor) if valor else None
        return cohesion

    def _cargar_ejes(self):
        data = yaml.safe_load(EJES_PATH.read_text(encoding="utf-8")) or {}
        return {str(k): v for k, v in data.items()}

    def _cargar_y_agregar_votos(self):
        with open(VOTOS_PATH, encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                if fila["categoria_votacion"] != "FONDO_GENERAL":
                    continue
                voto = fila["voto"]
                if voto not in POSICIONES_VALIDAS:
                    continue

                id_ = fila["id_diputado"]
                bloque = fila["bloque_canonico_en_esa_fecha"]
                eje = self._ejes_por_acta.get(fila["acta_id"])  # None si no está en las 13 etiquetadas
                subgrupo = self._subgrupo.get(id_)
                es_afirmativo = 1 if voto == "AFIRMATIVO" else 0

                # siempre suma al bucket general (eje=None); además, si esta
                # acta tiene eje asignado, suma también al bucket de ese eje
                for clave_eje in {None, eje}:
                    self._agg_individual[id_][clave_eje][0] += 1
                    self._agg_individual[id_][clave_eje][1] += es_afirmativo
                    self._agg_bloque[bloque][clave_eje][0] += 1
                    self._agg_bloque[bloque][clave_eje][1] += es_afirmativo
                    if subgrupo is not None:
                        self._agg_subgrupo[subgrupo][clave_eje][0] += 1
                        self._agg_subgrupo[subgrupo][clave_eje][1] += es_afirmativo

    # ------------------------------------------------------------------
    # consultas
    # ------------------------------------------------------------------

    def universo_diputados(self) -> list:
        return list(self._universo)

    def nombre_de(self, id_diputado: str) -> str:
        return self._nombres[id_diputado]

    def bloque_actual_de(self, id_diputado: str) -> str:
        return self._bloque_actual[id_diputado]

    def subgrupo_de(self, id_diputado: str) -> Optional[int]:
        return self._subgrupo.get(id_diputado)

    def cohesion_de_bloque(self, bloque: str) -> Optional[float]:
        return self._cohesion.get(bloque)

    def miembros_de_bloque(self, bloque: str) -> list:
        return [i for i in self._universo if self._bloque_actual[i] == bloque]

    def _tasa(self, agg: dict, clave, eje: Optional[str]) -> TasaEvidencia:
        n, afirmativos = agg[clave][eje]
        p = (afirmativos / n) if n > 0 else 0.5  # n=0 -> p irrelevante, el shrinkage lo anula
        return TasaEvidencia(p, n)

    def tasa_individual(self, id_diputado: str, eje: Optional[str] = None) -> TasaEvidencia:
        return self._tasa(self._agg_individual, id_diputado, eje)

    def tasa_subgrupo(self, subgrupo: int, eje: Optional[str] = None) -> TasaEvidencia:
        return self._tasa(self._agg_subgrupo, subgrupo, eje)

    def tasa_bloque(self, bloque: str, eje: Optional[str] = None) -> TasaEvidencia:
        return self._tasa(self._agg_bloque, bloque, eje)
