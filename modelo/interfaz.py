#!/usr/bin/env python3
"""Interfaz del modelo de poroteo.

Separa QUÉ se predice (este archivo) de CÓMO se predice (las
implementaciones concretas: ModeloPromedios ahora, ModeloBayesiano con
PyMC después). Todo el resto del sistema — el orquestador del poroteo
(poroteo.py), la carga de OD, la salida — habla contra ModeloPoroteo,
nunca contra una implementación concreta. Cambiar de motor es cambiar
qué clase se instancia en un solo lugar, no reescribir el resto.

No importa nada de promedios.py ni de datos_evidencia.py — este módulo
no sabe cómo se calcula nada, solo define la forma del contrato.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CargaOD:
    """Carga manual de una Orden del Día, para el modo "con OD". Los ids
    en cada lista son id_diputado (el id estable de ingesta/tabla_maestra_diputados.json)."""

    numero: str
    titulo: str
    mayoria: tuple = ()              # firmantes que suscriben el dictamen de mayoría -> ancla afirmativo
    minoria: tuple = ()              # firmantes de un dictamen de minoría -> ancla negativo
    disidencia_parcial: tuple = ()   # -> ancla afirmativo en general (con matices)
    disidencia_total: tuple = ()     # -> ancla negativo


@dataclass(frozen=True)
class Votacion:
    """Lo que se quiere proyectar.

    Modo sin OD: solo título (y opcionalmente eje ya asignado a mano).
    Modo con OD: además trae `od` con los firmantes.
    """

    titulo: str
    eje: Optional[str] = None  # si es None, el modelo decide cómo resolverlo (ver promedios.py)
    od: Optional[CargaOD] = None


@dataclass(frozen=True)
class PrediccionLegislador:
    """Salida del modelo para UN legislador, ante UNA votación."""

    id_diputado: str
    probabilidad_afirmativo: float          # en [0, 1]
    banda_confianza: tuple                  # (low, high), ambos en [0, 1]
    n_evidencia_efectiva: float             # cantidad de evidencia ponderada detrás de la estimación
    fuente_dominante: str                   # "individual" | "subgrupo" | "bloque" | "ancla_od" | "propagado_od"

    @property
    def ancho_banda(self) -> float:
        return self.banda_confianza[1] - self.banda_confianza[0]


class ModeloPoroteo(ABC):
    """Contrato que debe cumplir cualquier motor de poroteo (promedios
    ponderados hoy, bayesiano con PyMC después)."""

    @abstractmethod
    def predecir(self, votacion: Votacion) -> dict:
        """Para cada legislador del universo del modelo, devuelve su
        PrediccionLegislador para `votacion`.

        Devuelve dict[id_diputado, PrediccionLegislador].
        """
        raise NotImplementedError
