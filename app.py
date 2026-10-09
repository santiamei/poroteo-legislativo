#!/usr/bin/env python3
"""App de Streamlit: poroteo legislativo (Cámara de Diputados de la Nación).

Carga SOLO el artefacto precalculado (modelo/artefacto_evidencia.json) —
nunca datos crudos, nunca reentrena nada. Habla exclusivamente con la
interfaz ModeloPoroteo (modelo/interfaz.py): no importa ModeloPromedios
en ningún punto de la lógica de armado de resultado, solo lo instancia
una vez al cargar el motor.
"""

import streamlit as st

from modelo.datos_evidencia import RepositorioEvidencia
from modelo.interfaz import CargaOD, Votacion
from modelo.matcheo_nombres import matchear_nombres
from modelo.poroteo import armar_resultado
from modelo.promedios import ModeloPromedios

MAYORIA_ABSOLUTA = 129  # mitad + 1 de 257 bancas

st.set_page_config(page_title="Poroteo Legislativo", page_icon="🫘", layout="wide")


@st.cache_resource
def cargar_motor():
    evidencia = RepositorioEvidencia.desde_artefacto()
    modelo = ModeloPromedios(evidencia)
    return evidencia, modelo


def mostrar_cartel_honesto():
    st.info(
        "**Herramienta en desarrollo**, sobre datos públicos de la Cámara de Diputados "
        "(vía [Data CP](https://www.datacp.ar)), ventana **10/12/2025 – 27/08/2026**. "
        "Es un modelo v1 por promedios ponderados, no un modelo bayesiano completo. "
        "**El total proyectado es bastante más confiable que la predicción de cada "
        "legislador en particular** — tratá las probabilidades individuales como una "
        "guía de dónde mirar, no como un pronóstico exacto.",
        icon="⚠️",
    )


def mostrar_resultado(resultado, evidencia):
    pt = resultado.proyeccion_total

    st.subheader("Proyección total")
    col1, col2, col3 = st.columns(3)
    col1.metric("Afirmativos esperados", f"{pt.afirmativos_esperados:.1f}",
                f"{pt.afirmativos_esperados - MAYORIA_ABSOLUTA:+.1f} vs. mayoría ({MAYORIA_ABSOLUTA})")
    col2.metric("Negativos esperados", f"{pt.negativos_esperados:.1f}")
    col3.metric("Rango de afirmativos", f"{pt.rango_afirmativos[0]:.0f} – {pt.rango_afirmativos[1]:.0f}")

    low, high = pt.rango_afirmativos
    if low >= MAYORIA_ABSOLUTA:
        st.success(f"✅ Se proyecta **aprobada con margen** — incluso el extremo bajo del rango "
                   f"({low:.0f}) supera la mayoría de {MAYORIA_ABSOLUTA}.")
    elif high < MAYORIA_ABSOLUTA:
        st.error(f"❌ Se proyecta **no alcanza la mayoría** — incluso el extremo alto del rango "
                 f"({high:.0f}) queda por debajo de {MAYORIA_ABSOLUTA}.")
    else:
        st.warning(f"⚠️ **Resultado incierto** — el rango ({low:.0f}–{high:.0f}) cruza la línea "
                   f"de mayoría ({MAYORIA_ABSOLUTA}).")

    st.subheader("Desglose por bloque")
    filas_bloque = []
    for bloque, p in sorted(resultado.desglose_por_bloque.items(), key=lambda kv: -kv[1].n_miembros):
        filas_bloque.append({
            "Bloque": bloque,
            "Afirm. esperados": round(p.afirmativos_esperados, 1),
            "Miembros": p.n_miembros,
            "Proporción": p.afirmativos_esperados / p.n_miembros if p.n_miembros else 0.0,
            "Rango": f"{p.rango_afirmativos[0]:.1f} – {p.rango_afirmativos[1]:.1f}",
        })
    st.dataframe(
        filas_bloque,
        column_config={
            "Proporción": st.column_config.ProgressColumn(
                "Proporción afirm.", min_value=0.0, max_value=1.0, format="%.0f%%"
            ),
        },
        hide_index=True,
        width="stretch",
    )

    st.subheader("Legisladores ordenados por incertidumbre")
    st.caption('"Andá a hablar con estos": los que tienen la banda más ancha, no los que votan más parejo.')
    top_n = st.slider("Cuántos mostrar", 5, len(resultado.ranking_incertidumbre), 30, key="top_n_incertidumbre")
    filas_leg = []
    for pred in resultado.ranking_incertidumbre[:top_n]:
        filas_leg.append({
            "Legislador": evidencia.nombre_de(pred.id_diputado),
            "Bloque": evidencia.bloque_actual_de(pred.id_diputado),
            "Probabilidad afirm.": round(pred.probabilidad_afirmativo, 2),
            "Banda": f"{pred.banda_confianza[0]:.2f} – {pred.banda_confianza[1]:.2f}",
            "Ancho de banda": round(pred.ancho_banda, 2),
            "Fuente": pred.fuente_dominante,
        })
    st.dataframe(
        filas_leg,
        column_config={
            "Probabilidad afirm.": st.column_config.ProgressColumn(
                "Probabilidad afirm.", min_value=0.0, max_value=1.0, format="%.0f%%"
            ),
        },
        hide_index=True,
        width="stretch",
    )


def mostrar_problemas_matcheo(etiqueta, resultado_matcheo):
    if resultado_matcheo.sin_match:
        st.warning(f"**{etiqueta} — sin match** (no se anclaron, el modelo los predice por historial normal): "
                   + ", ".join(resultado_matcheo.sin_match))
    if resultado_matcheo.ambiguos:
        for texto, candidatos in resultado_matcheo.ambiguos.items():
            opciones = ", ".join(f"{c.nombre_canonico} ({c.id_diputado})" for c in candidatos)
            st.warning(f"**{etiqueta} — ambiguo**: {texto!r} podría ser {opciones}. "
                       "No se ancló ninguno — escribí el nombre completo o agregá la inicial.")


def main():
    st.title("🫘 Poroteo Legislativo")
    st.caption("Cámara de Diputados de la Nación Argentina — proyección de votos por promedios ponderados")
    mostrar_cartel_honesto()

    evidencia, modelo = cargar_motor()

    tab_sin_od, tab_con_od = st.tabs(["📊 Sin OD (por tendencia histórica)", "📝 Con OD (carga de firmantes)"])

    with tab_sin_od:
        st.markdown("Proyecta usando el historial de cada legislador, su subgrupo y su bloque — sin ningún "
                    "dictamen cargado. Elegí el eje temático más parecido al tema que querés proyectar.")
        n_actas_eje = evidencia.n_actas_por_eje()
        opciones_eje = ["(general — todos los temas de fondo)"] + sorted(n_actas_eje)
        etiquetas = {
            "(general — todos los temas de fondo)": "General (todos los temas de fondo)",
            **{e: f"{e} ({n_actas_eje[e]} actas históricas)" for e in n_actas_eje},
        }
        eje_sel = st.selectbox("Eje temático", opciones_eje, format_func=lambda e: etiquetas[e])
        eje = None if eje_sel.startswith("(general") else eje_sel

        if st.button("Proyectar", key="btn_sin_od", type="primary"):
            votacion = Votacion(titulo=f"Proyección sin OD — {etiquetas[eje_sel]}", eje=eje)
            resultado = armar_resultado(modelo, votacion, evidencia)
            mostrar_resultado(resultado, evidencia)

    with tab_con_od:
        st.markdown("Pegá los firmantes del dictamen (uno por línea: apellido solo, `Inicial. Apellido`, "
                    "`Nombre Apellido`, o apellido compuesto). Los que no matcheen quedan listados, no se fuerzan.")

        col_num, col_tit = st.columns([1, 3])
        numero_od = col_num.text_input("N° de OD (opcional)")
        titulo_od = col_tit.text_input("Título (opcional)", placeholder="Para identificar la proyección")

        n_actas_eje = evidencia.n_actas_por_eje()
        opciones_eje_od = sorted(n_actas_eje)
        etiquetas_od = {e: f"{e} ({n_actas_eje[e]} actas históricas)" for e in opciones_eje_od}
        eje_od = st.selectbox("Eje temático de esta OD", opciones_eje_od,
                               format_func=lambda e: etiquetas_od[e], key="eje_od")

        c1, c2 = st.columns(2)
        texto_mayoria = c1.text_area("Mayoría (ancla afirmativo)", height=150,
                                      placeholder="Un nombre por línea, ej:\nPetri\nBornoroni")
        texto_minoria = c2.text_area("Minoría (ancla negativo)", height=150,
                                      placeholder="Un nombre por línea")
        c3, c4 = st.columns(2)
        texto_disid_parcial = c3.text_area("Disidencia parcial (ancla afirmativo moderado)", height=100)
        texto_disid_total = c4.text_area("Disidencia total (ancla negativo moderado)", height=100)

        if st.button("Cargar y predecir", key="btn_con_od", type="primary"):
            nombres_universo = {i: evidencia.nombre_de(i) for i in evidencia.universo_diputados()}

            m_mayoria = matchear_nombres(texto_mayoria.splitlines(), nombres_universo)
            m_minoria = matchear_nombres(texto_minoria.splitlines(), nombres_universo)
            m_disid_parcial = matchear_nombres(texto_disid_parcial.splitlines(), nombres_universo)
            m_disid_total = matchear_nombres(texto_disid_total.splitlines(), nombres_universo)

            mostrar_problemas_matcheo("Mayoría", m_mayoria)
            mostrar_problemas_matcheo("Minoría", m_minoria)
            mostrar_problemas_matcheo("Disidencia parcial", m_disid_parcial)
            mostrar_problemas_matcheo("Disidencia total", m_disid_total)

            total_anclados = len(m_mayoria.ids) + len(m_minoria.ids) + len(m_disid_parcial.ids) + len(m_disid_total.ids)
            if total_anclados == 0:
                st.error("Ningún nombre matcheó — no hay nada que anclar. Revisá el texto pegado.")
            else:
                st.caption(f"{total_anclados} firmantes anclados correctamente.")
                od = CargaOD(
                    numero=numero_od or "(sin número)",
                    titulo=titulo_od or "(sin título)",
                    mayoria=m_mayoria.ids,
                    minoria=m_minoria.ids,
                    disidencia_parcial=m_disid_parcial.ids,
                    disidencia_total=m_disid_total.ids,
                )
                votacion = Votacion(titulo=titulo_od or f"OD {numero_od}", eje=eje_od, od=od)
                resultado = armar_resultado(modelo, votacion, evidencia)
                mostrar_resultado(resultado, evidencia)


if __name__ == "__main__":
    main()
