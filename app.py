#!/usr/bin/env python3
"""App de Streamlit: poroteo legislativo (Cámara de Diputados de la Nación).

Etapa 4: Streamlit queda como MOTOR, no como UI. Tres pantallas, todas
con la identidad visual de plantilla_resultado.html (la plantilla
aprobada):

  carga      -> sube el PDF de la OD.
  revision   -> firmantes detectados por tipo, revisables/corregibles
                (reutiliza matcheo_nombres.py), confirmación si
                hay_problemas, botón "Proyectar".
  resultado  -> plantilla_resultado.html 100% HTML/SVG/JS, rellenada con
                el JSON real (construir_datos_resultado), montada vía
                st.components.v1.html.

Carga y revisión usan un MÍNIMO de widgets nativos de Streamlit
(file_uploader para poder leer el PDF en Python; multiselect/text_area/
checkbox/button para la corrección) porque components.v1.html es de solo
lectura -- no tiene forma de devolver datos a Python sin construir un
componente bidireccional propio. Van restyleados con la misma paleta/
tipografía de la plantilla para que las tres pantallas se sientan como
un solo producto. El resultado es 100% la plantilla aprobada, sin tocar.

Nunca decide nada por su cuenta: el parseo del PDF, el matcheo de
nombres, la selección de tema y el modelo son los mismos módulos ya
validados en etapas anteriores.
"""

import json
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from modelo.datos_evidencia import RepositorioEvidencia
from modelo.interfaz import CargaOD, Votacion
from modelo.matcheo_nombres import matchear_nombres
from modelo.parseo_od import (
    TIPO_DISIDENCIA_PARCIAL,
    TIPO_DISIDENCIA_TOTAL,
    TIPO_MAYORIA,
    TIPO_MINORIA,
    parsear_od_pdf,
)
from modelo.poroteo import armar_resultado
from modelo.promedios import ModeloPromedios
from modelo.seleccion_tema import seleccionar_tema_para_od
from presentacion import cargar_colores_bloques, cargar_escala_voto, construir_datos_resultado

BASE_DIR = Path(__file__).parent
PLANTILLA_RESULTADO_PATH = BASE_DIR / "plantilla_resultado.html"

ETIQUETAS_TIPO = {
    TIPO_MAYORIA: "Mayoría",
    TIPO_MINORIA: "Minoría",
    TIPO_DISIDENCIA_PARCIAL: "Disidencia parcial",
    TIPO_DISIDENCIA_TOTAL: "Disidencia total",
}
ICONOS_TIPO = {
    TIPO_MAYORIA: "✓",
    TIPO_MINORIA: "✗",
    TIPO_DISIDENCIA_PARCIAL: "±",
    TIPO_DISIDENCIA_TOTAL: "∓",
}

st.set_page_config(page_title="Poroteo Legislativo", page_icon="🫘", layout="wide")


@st.cache_resource
def cargar_motor():
    evidencia = RepositorioEvidencia.desde_artefacto()
    modelo = ModeloPromedios(evidencia)
    return evidencia, modelo


# ---------------------------------------------------------------------------
# identidad visual compartida (carga + revisión; el resultado trae la suya
# propia adentro de plantilla_resultado.html)
# ---------------------------------------------------------------------------

CSS_GLOBAL = """
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600;700&display=swap">
<style>
:root {
  --pm-bg: #eef1f6; --pm-surface: #ffffff; --pm-surface-2: #f6f8fb;
  --pm-fg: #1a2234; --pm-fg-muted: #5c6880;
  --pm-border: #dde3ec; --pm-border-strong: #c7cfdd;
  --pm-accent: #3a4e7a; --pm-accent-soft: #e8ecf5;
  --pm-font-display: 'Fraunces', Georgia, serif;
  --pm-font-body: 'Inter', system-ui, -apple-system, sans-serif;
}
.stApp { background: var(--pm-bg); }
.pm-masthead { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 4px; }
.pm-brand { font-family: var(--pm-font-display); font-weight: 600; font-size: clamp(24px,4vw,30px);
            letter-spacing: -.01em; color: var(--pm-fg); }
.pm-pill { font-size: 10.5px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase;
           color: var(--pm-accent); background: var(--pm-accent-soft); padding: 4px 9px; border-radius: 999px; }
.pm-tagline { font-size: 15px; color: var(--pm-fg-muted); max-width: 60ch; margin: 10px 0 26px; font-family: var(--pm-font-body); }
.pm-card { background: var(--pm-surface); border: 1px solid var(--pm-border); border-radius: 12px;
           padding: 16px 18px; margin-bottom: 14px; }
.pm-card h3 { font-family: var(--pm-font-display); font-size: 16px; font-weight: 600; margin: 0 0 4px; color: var(--pm-fg); }
.pm-card .pm-count { font-size: 12.5px; color: var(--pm-fg-muted); font-family: var(--pm-font-body); }
.pm-disclaimer { font-size: 11.5px; color: var(--pm-fg-muted); border-top: 1px solid var(--pm-border);
                 padding-top: 12px; margin-top: 16px; line-height: 1.45; font-family: var(--pm-font-body); }
.pm-od-line { font-size: 13px; color: var(--pm-fg-muted); margin: 10px 0 2px; font-family: var(--pm-font-body); }
.pm-od-title { font-size: 15px; font-weight: 500; color: var(--pm-fg); max-width: 60ch; margin-bottom: 18px;
               font-family: var(--pm-font-body); }

/* restyle de los widgets nativos imprescindibles para que no desentonen */
div[data-testid="stFileUploaderDropzone"] {
  background: var(--pm-surface); border: 2px dashed var(--pm-border-strong); border-radius: 14px;
}
div[data-testid="stButton"] button[kind="primary"] {
  background: var(--pm-accent); border-radius: 9px; font-family: var(--pm-font-body); font-weight: 600;
}
div[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
  background-color: var(--pm-accent-soft) !important; color: var(--pm-accent) !important;
}
</style>
"""


def _inyectar_css_global():
    st.markdown(CSS_GLOBAL, unsafe_allow_html=True)


def _masthead_html(pill_texto: str, tagline: str) -> str:
    return (
        f'<div class="pm-masthead"><span class="pm-brand">Poroteo</span>'
        f'<span class="pm-pill">{pill_texto}</span></div>'
        f'<p class="pm-tagline">{tagline}</p>'
    )


DISCLAIMER_HTML = (
    '<div class="pm-disclaimer">Herramienta en desarrollo. Datos públicos de la Cámara de Diputados '
    "(vía Data CP). Composición y votaciones de la ventana 10/12/2025 – 27/08/2026. "
    "El total proyectado es más confiable que cada voto individual.</div>"
)


# ---------------------------------------------------------------------------
# pantalla: carga
# ---------------------------------------------------------------------------


def _procesar_pdf_subido(archivo, nombres_universo):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(archivo.getvalue())
        ruta_tmp = tmp.name
    try:
        resultado_parseo = parsear_od_pdf(ruta_tmp, nombres_universo)
    finally:
        Path(ruta_tmp).unlink(missing_ok=True)

    st.session_state["_od_firma"] = f"{archivo.name}_{archivo.size}"
    st.session_state["resultado_parseo"] = resultado_parseo
    st.session_state["resultado"] = None
    st.session_state["od_actual"] = None
    st.session_state["pantalla"] = "revision"


def pantalla_carga(nombres_universo):
    st.markdown(
        _masthead_html(
            "Cargar OD",
            "Subí el PDF de una Orden del Día y proyectamos cómo vota cada diputado — "
            "a partir de las firmas del dictamen y el historial de voto por bloque.",
        ),
        unsafe_allow_html=True,
    )

    archivo = st.file_uploader(
        "Subí el PDF de la Orden del Día", type=["pdf"], label_visibility="collapsed"
    )
    if archivo is not None:
        try:
            with st.spinner("Leyendo el PDF..."):
                _procesar_pdf_subido(archivo, nombres_universo)
        except Exception as e:  # PDF corrupto/con formato inesperado: no tirar la app
            st.error(f"No se pudo leer el PDF: {e}")
        else:
            st.rerun()

    st.markdown(DISCLAIMER_HTML, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# pantalla: revisión de firmas
# ---------------------------------------------------------------------------


def _panel_firmantes(tipo, resultado_parseo, nombres_universo, sufijo_key):
    etiqueta = ETIQUETAS_TIPO[tipo]
    icono = ICONOS_TIPO[tipo]
    r = resultado_parseo.matcheo[tipo]
    opciones_ids = list(r.matcheados.values())
    etiquetas_por_id = {id_: nombres_universo.get(id_, id_) for id_ in opciones_ids}

    st.markdown(
        f'<div class="pm-card"><h3>{icono} {etiqueta}</h3>'
        f'<div class="pm-count">{len(opciones_ids)} detectado(s) con confianza — sacá los que estén mal.</div></div>',
        unsafe_allow_html=True,
    )
    seleccionados = st.multiselect(
        etiqueta,
        options=opciones_ids,
        default=opciones_ids,
        format_func=lambda id_: etiquetas_por_id.get(id_, id_),
        key=f"sel_{tipo}_{sufijo_key}",
        label_visibility="collapsed",
    )

    ids_corregidos = []
    pendientes = list(r.sin_match) + list(r.ambiguos.keys())
    if pendientes:
        st.warning(f"⚠️ {len(pendientes)} nombre(s) de {etiqueta.lower()} no se pudieron matchear solos.")
        texto_corregido = st.text_area(
            f"Corregí o completá (uno por línea) — {etiqueta}",
            value="\n".join(pendientes),
            key=f"correccion_{tipo}_{sufijo_key}",
            height=80,
        )
        correccion = matchear_nombres(texto_corregido.splitlines(), nombres_universo)
        ids_corregidos = list(correccion.ids)
        if correccion.sin_match:
            st.caption(f"Todavía sin matchear: {', '.join(correccion.sin_match)}")
        for texto_amb, candidatos in correccion.ambiguos.items():
            op = ", ".join(f"{c.nombre_canonico} ({c.id_diputado})" for c in candidatos)
            st.caption(f"⚠️ '{texto_amb}' sigue siendo ambiguo: podría ser {op}. Escribí el nombre completo.")

    return tuple(dict.fromkeys(list(seleccionados) + ids_corregidos))


def pantalla_revision(evidencia, modelo, nombres_universo):
    resultado_parseo = st.session_state.get("resultado_parseo")
    firma = st.session_state.get("_od_firma", "sin_firma")

    st.markdown(
        _masthead_html("Revisión de firmas", "El sistema propone, vos confirmás. Revisá antes de proyectar."),
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="pm-od-line">Orden del Día N° <b>{resultado_parseo.numero_od or "(sin número)"}</b></div>'
        f'<div class="pm-od-title">{resultado_parseo.titulo or ""}</div>',
        unsafe_allow_html=True,
    )

    ids_por_tipo = {}
    for tipo in (TIPO_MAYORIA, TIPO_MINORIA, TIPO_DISIDENCIA_PARCIAL, TIPO_DISIDENCIA_TOTAL):
        ids_por_tipo[tipo] = _panel_firmantes(tipo, resultado_parseo, nombres_universo, firma)

    confirmado = True
    if resultado_parseo.hay_problemas:
        confirmado = st.checkbox(
            "☑️ Confirmo que revisé los firmantes detectados "
            "(hay secciones de baja confianza o nombres sin resolver)",
            key=f"confirmacion_{firma}",
        )

    col1, col2 = st.columns([1, 1])
    if col1.button("← Cargar otra OD"):
        for clave in ("resultado_parseo", "_od_firma", "resultado", "od_actual"):
            st.session_state.pop(clave, None)
        st.session_state["pantalla"] = "carga"
        st.rerun()

    if col2.button("Proyectar →", type="primary", disabled=not confirmado):
        od = CargaOD(
            numero=resultado_parseo.numero_od or "(sin número)",
            titulo=resultado_parseo.titulo or "(sin título)",
            mayoria=ids_por_tipo[TIPO_MAYORIA],
            minoria=ids_por_tipo[TIPO_MINORIA],
            disidencia_parcial=ids_por_tipo[TIPO_DISIDENCIA_PARCIAL],
            disidencia_total=ids_por_tipo[TIPO_DISIDENCIA_TOTAL],
        )
        seleccion_tema = seleccionar_tema_para_od(resultado_parseo.titulo or "", evidencia)
        # auditoría interna -- nunca se muestra en la UI (ver modelo/seleccion_tema.py)
        print(
            f"[seleccion_tema] OD {od.numero}: grupo={seleccion_tema.seleccion.grupo!r} "
            f"confianza={seleccion_tema.seleccion.confianza} n_actas={seleccion_tema.n_actas} "
            f"palabras={seleccion_tema.seleccion.palabras_matcheadas}"
        )
        votacion = Votacion(titulo=od.titulo, eje=seleccion_tema.eje_para_modelo, od=od)
        st.session_state["resultado"] = armar_resultado(modelo, votacion, evidencia)
        st.session_state["od_actual"] = od
        st.session_state["pantalla"] = "resultado"
        st.rerun()

    st.markdown(DISCLAIMER_HTML, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# pantalla: resultado (100% plantilla_resultado.html)
# ---------------------------------------------------------------------------


def pantalla_resultado(evidencia, colores_bloques, escala_voto):
    resultado = st.session_state.get("resultado")
    resultado_parseo = st.session_state.get("resultado_parseo")
    od_actual = st.session_state.get("od_actual")

    if st.button("← Nueva proyección"):
        for clave in ("resultado_parseo", "_od_firma", "resultado", "od_actual"):
            st.session_state.pop(clave, None)
        st.session_state["pantalla"] = "carga"
        st.rerun()

    datos = construir_datos_resultado(resultado, evidencia, resultado_parseo, colores_bloques, escala_voto, od_actual)
    plantilla = PLANTILLA_RESULTADO_PATH.read_text(encoding="utf-8")
    html = plantilla.replace("__DATA_JSON__", json.dumps(datos, ensure_ascii=False))
    components.html(html, height=1500, scrolling=True)


# ---------------------------------------------------------------------------


def main():
    _inyectar_css_global()

    colores_bloques = cargar_colores_bloques()
    escala_voto = cargar_escala_voto()
    evidencia, modelo = cargar_motor()
    nombres_universo = {i: evidencia.nombre_de(i) for i in evidencia.universo_diputados()}

    pantalla = st.session_state.get("pantalla", "carga")

    if pantalla == "revision" and st.session_state.get("resultado_parseo") is None:
        pantalla = "carga"  # estado inconsistente (ej. recarga de página): volver al inicio
    if pantalla == "resultado" and st.session_state.get("resultado") is None:
        pantalla = "carga"

    if pantalla == "carga":
        pantalla_carga(nombres_universo)
    elif pantalla == "revision":
        pantalla_revision(evidencia, modelo, nombres_universo)
    elif pantalla == "resultado":
        pantalla_resultado(evidencia, colores_bloques, escala_voto)


if __name__ == "__main__":
    main()
