#!/usr/bin/env python3
"""Repositorio de evidencia histórica: individual / subgrupo / bloque.

Separado del modelo a propósito: ModeloPromedios y el futuro
ModeloBayesiano (PyMC) consumen la MISMA evidencia sin duplicar la carga
de datos. Este módulo solo lee y expone tasas — no pondera ni combina
nada, eso es responsabilidad del modelo (promedios.py).

Dos formas de construirlo, misma interfaz pública en ambas — nada que
consuma RepositorioEvidencia (ModeloPromedios, poroteo.py) sabe ni le
importa cuál se usó:

  RepositorioEvidencia()                    — pipeline completo, lee los
      CSV/JSON crudos de ingesta/ y data/processed/. Pesado, solo para
      correr local/offline (ver generar_artefacto.py).
  RepositorioEvidencia.desde_artefacto(path) — reconstruye el mismo
      estado ya agregado desde un JSON liviano (modelo/artefacto_evidencia.json).
      Esto es lo que usa la app de Streamlit: no toca data/raw ni
      data/processed (ni existen en el deploy).

Fuentes del pipeline completo:
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
El artefacto solo lleva nombres/evidencia de este universo (257) — no de
los 259 que aparecieron alguna vez en la ventana.
"""

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "processed"
INGESTA_DIR = BASE_DIR / "ingesta"
CLASIFICACION_DIR = BASE_DIR / "clasificacion"
MODELO_DIR = Path(__file__).parent

VOTOS_PATH = DATA_DIR / "votos_consolidado.csv"
TABLA_MAESTRA_PATH = INGESTA_DIR / "tabla_maestra_diputados.json"
MAPEO_BLOQUES_PATH = INGESTA_DIR / "mapeo_bloques_diputados.json"
COHESION_PATH = DATA_DIR / "cohesion_bloques_fondo_general.csv"
CLUSTERS_PATH = DATA_DIR / "clusters_conflicto_13actas.csv"
EJES_PATH = CLASIFICACION_DIR / "ejes_manuales.yaml"
GRUPOS_TEMATICOS_PATH = CLASIFICACION_DIR / "grupos_tematicos.yaml"
ARTEFACTO_PATH_DEFAULT = MODELO_DIR / "artefacto_evidencia.json"

CORTE_SUBGRUPO_K = 8  # confirmado con el usuario
POSICIONES_VALIDAS = {"AFIRMATIVO", "NEGATIVO", "ABSTENCION"}
FECHA_FIN_VENTANA = "27/08/2026"

# JSON no admite `null` como clave de objeto; este sentinel representa el
# bucket "general" (eje=None) al serializar/deserializar el artefacto.
SENTINEL_EJE_GENERAL = "_general_"


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

    def __init__(self, excluir_actas=frozenset()):
        """excluir_actas: acta_ids a excluir de TODA la evidencia agregada
        (individual/subgrupo/bloque, general y por-eje). Para validación
        honesta contra una acta real: sacarla del entrenamiento antes de
        predecirla, no es un ajuste del modelo — es no memorizarla.

        Pipeline completo (lee CSV/JSON crudos). Para cargar desde el
        artefacto liviano, usar RepositorioEvidencia.desde_artefacto()."""
        self._excluir_actas = frozenset(excluir_actas)
        self._nombres = self._cargar_nombres()
        self._bloque_actual, self._universo = self._cargar_bloque_actual_y_universo()
        self._subgrupo = self._cargar_subgrupo()
        self._cohesion = self._cargar_cohesion()
        self._ejes_por_acta = self._cargar_ejes()
        self._eje_a_grupo = self._cargar_eje_a_grupo()

        # agregados[nivel][clave][eje_o_grupo_o_None] = [n, afirmativos]
        # el grupo temático grueso (ver grupos_tematicos.yaml) vive en el
        # MISMO espacio de claves que el eje fino -- sus ids ("economico",
        # "regulacion_produccion", "institucional_derechos") no chocan con
        # ningún nombre de eje real ("Económico/fiscal", etc.), así que
        # tasa_individual(id, eje="economico") funciona sin tocar nada más
        # en el modelo (promedios.py) ni en la serialización del artefacto.
        self._agg_individual = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        self._agg_subgrupo = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        self._agg_bloque = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        self._actas_por_eje = defaultdict(set)
        self._actas_por_grupo = defaultdict(set)
        self._actas_generales = set()
        self._cargar_y_agregar_votos()

        self._ejes_disponibles = sorted(self._actas_por_eje.keys())
        self._n_actas_por_eje = {eje: len(actas) for eje, actas in self._actas_por_eje.items()}
        self._grupos_disponibles = sorted(self._actas_por_grupo.keys())
        self._n_actas_por_grupo = {g: len(actas) for g, actas in self._actas_por_grupo.items()}
        self._n_actas_generales = len(self._actas_generales)

    # ------------------------------------------------------------------
    # carga (pipeline completo, offline)
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
        import yaml  # import local: la app (desde_artefacto) no necesita PyYAML

        data = yaml.safe_load(EJES_PATH.read_text(encoding="utf-8")) or {}
        return {str(k): v for k, v in data.items()}

    def _cargar_eje_a_grupo(self):
        import yaml  # import local: la app (desde_artefacto) no necesita PyYAML

        data = yaml.safe_load(GRUPOS_TEMATICOS_PATH.read_text(encoding="utf-8")) or {}
        eje_a_grupo = {}
        for grupo, info in data.items():
            for eje in (info or {}).get("ejes", []):
                eje_a_grupo[eje] = grupo
        return eje_a_grupo

    def _cargar_y_agregar_votos(self):
        with open(VOTOS_PATH, encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                if fila["categoria_votacion"] != "FONDO_GENERAL":
                    continue
                if fila["acta_id"] in self._excluir_actas:
                    continue
                voto = fila["voto"]
                if voto not in POSICIONES_VALIDAS:
                    continue

                id_ = fila["id_diputado"]
                bloque = fila["bloque_canonico_en_esa_fecha"]
                eje = self._ejes_por_acta.get(fila["acta_id"])  # None si no está en las 13 etiquetadas
                grupo = self._eje_a_grupo.get(eje) if eje is not None else None
                subgrupo = self._subgrupo.get(id_)
                es_afirmativo = 1 if voto == "AFIRMATIVO" else 0

                self._actas_generales.add(fila["acta_id"])
                if eje is not None:
                    self._actas_por_eje[eje].add(fila["acta_id"])
                if grupo is not None:
                    self._actas_por_grupo[grupo].add(fila["acta_id"])

                # siempre suma al bucket general (clave=None); además, si
                # esta acta tiene eje y/o grupo asignado, suma también a
                # esos buckets (ver comentario en __init__ sobre por qué el
                # grupo comparte espacio de claves con el eje fino)
                for clave_eje in {None, eje, grupo}:
                    self._agg_individual[id_][clave_eje][0] += 1
                    self._agg_individual[id_][clave_eje][1] += es_afirmativo
                    self._agg_bloque[bloque][clave_eje][0] += 1
                    self._agg_bloque[bloque][clave_eje][1] += es_afirmativo
                    if subgrupo is not None:
                        self._agg_subgrupo[subgrupo][clave_eje][0] += 1
                        self._agg_subgrupo[subgrupo][clave_eje][1] += es_afirmativo

    # ------------------------------------------------------------------
    # artefacto liviano (lo que usa la app)
    # ------------------------------------------------------------------

    @staticmethod
    def _serializar_agg(agg: dict) -> dict:
        salida = {}
        for clave, por_eje in agg.items():
            salida[str(clave)] = {
                (SENTINEL_EJE_GENERAL if eje is None else eje): list(valores)
                for eje, valores in por_eje.items()
            }
        return salida

    @staticmethod
    def _deserializar_agg(crudo: dict, convertir_clave) -> dict:
        salida = {}
        for clave, por_eje in crudo.items():
            salida[convertir_clave(clave)] = {
                (None if eje == SENTINEL_EJE_GENERAL else eje): valores
                for eje, valores in por_eje.items()
            }
        return salida

    def exportar_artefacto(self, path=ARTEFACTO_PATH_DEFAULT) -> Path:
        """Serializa el estado ya agregado a un JSON liviano (decenas-cientos
        de KB, no los ~8.5 MB de votos_consolidado.csv). Pensado para
        commitear al repo y que la app lo cargue con desde_artefacto()."""
        datos = {
            "nombres": {i: self._nombres[i] for i in self._universo},
            "bloque_actual": {i: self._bloque_actual[i] for i in self._universo},
            "universo": list(self._universo),
            "subgrupo": dict(self._subgrupo),
            "cohesion": dict(self._cohesion),
            "ejes_disponibles": list(self._ejes_disponibles),
            "n_actas_por_eje": dict(self._n_actas_por_eje),
            "grupos_disponibles": list(self._grupos_disponibles),
            "n_actas_por_grupo": dict(self._n_actas_por_grupo),
            "n_actas_generales": self._n_actas_generales,
            "agg_individual": self._serializar_agg(self._agg_individual),
            "agg_subgrupo": self._serializar_agg(self._agg_subgrupo),
            "agg_bloque": self._serializar_agg(self._agg_bloque),
        }
        path = Path(path)
        path.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def desde_artefacto(cls, path=ARTEFACTO_PATH_DEFAULT) -> "RepositorioEvidencia":
        """Reconstruye el repositorio desde el artefacto liviano, sin tocar
        data/raw ni data/processed. Esto es lo que usa app.py."""
        datos = json.loads(Path(path).read_text(encoding="utf-8"))

        obj = cls.__new__(cls)
        obj._excluir_actas = frozenset()
        obj._nombres = dict(datos["nombres"])
        obj._bloque_actual = dict(datos["bloque_actual"])
        obj._universo = list(datos["universo"])
        obj._subgrupo = {k: int(v) for k, v in datos["subgrupo"].items()}
        obj._cohesion = dict(datos["cohesion"])
        obj._ejes_disponibles = list(datos["ejes_disponibles"])
        obj._n_actas_por_eje = dict(datos["n_actas_por_eje"])
        obj._grupos_disponibles = list(datos.get("grupos_disponibles", []))
        obj._n_actas_por_grupo = dict(datos.get("n_actas_por_grupo", {}))
        obj._n_actas_generales = datos.get("n_actas_generales", 0)
        obj._agg_individual = cls._deserializar_agg(datos["agg_individual"], str)
        obj._agg_subgrupo = cls._deserializar_agg(datos["agg_subgrupo"], int)
        obj._agg_bloque = cls._deserializar_agg(datos["agg_bloque"], str)
        return obj

    # ------------------------------------------------------------------
    # consultas (idénticas sin importar cómo se construyó el objeto)
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

    def ejes_disponibles(self) -> list:
        return list(self._ejes_disponibles)

    def n_actas_por_eje(self) -> dict:
        return dict(self._n_actas_por_eje)

    def grupos_disponibles(self) -> list:
        return list(self._grupos_disponibles)

    def n_actas_por_grupo(self) -> dict:
        return dict(self._n_actas_por_grupo)

    def n_actas_generales(self) -> int:
        """Total de actas FONDO_GENERAL de la ventana, tengan o no eje/
        grupo asignado -- el tamaño de la evidencia que usa la red de
        seguridad (clasificacion.grupo_tematico.GRUPO_GENERAL) cuando una
        OD no cae con confianza en ningún grupo."""
        return self._n_actas_generales

    def _tasa(self, agg: dict, clave, eje: Optional[str]) -> TasaEvidencia:
        n, afirmativos = agg.get(clave, {}).get(eje, [0, 0])
        p = (afirmativos / n) if n > 0 else 0.5  # n=0 -> p irrelevante, el shrinkage lo anula
        return TasaEvidencia(p, n)

    def tasa_individual(self, id_diputado: str, eje: Optional[str] = None) -> TasaEvidencia:
        return self._tasa(self._agg_individual, id_diputado, eje)

    def tasa_subgrupo(self, subgrupo: int, eje: Optional[str] = None) -> TasaEvidencia:
        return self._tasa(self._agg_subgrupo, subgrupo, eje)

    def tasa_bloque(self, bloque: str, eje: Optional[str] = None) -> TasaEvidencia:
        return self._tasa(self._agg_bloque, bloque, eje)
