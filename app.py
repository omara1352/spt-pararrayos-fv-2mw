"""
App Streamlit: SPT + PECAR de una planta FV de 2 MW en Santa Fe de Antioquia.
Ejecutar:  streamlit run app.py
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from datos import DATOS, RADIO_ESFERA, EFICIENCIA_LPL, CONDUCTORES, PRECIOS, SUPUESTOS_POR_CONFIRMAR
from motor import Proyecto, MODOS_VARILLA, costo_mastil
import graficas as gr

AQUI = Path(__file__).parent
st.set_page_config(page_title="SPT y pararrayos - FV 2 MW Santa Fe de Antioquia", layout="wide")


# ------------------------------------------------------------------ datos de entrada (barra lateral)
st.sidebar.header("Paso 0 · Datos de entrada")
st.sidebar.caption("Se fijan antes de diseñar. Los marcados como supuesto se deben confirmar.")
d = dict(DATOS)
with st.sidebar.expander("Suelo y falla (IEEE 80)", expanded=True):
    d["resistividad_suelo"] = st.number_input("Resistividad del suelo ρ (Ω·m) · supuesto", 10.0, 5000.0,
                                              DATOS["resistividad_suelo"], 10.0)
    d["corriente_falla"] = st.number_input("Corriente máxima de malla IG (A)", 100.0, 40000.0,
                                           DATOS["corriente_falla"], 100.0)
    d["tiempo_despeje"] = st.number_input("Tiempo de despeje (s)", 0.05, 3.0, DATOS["tiempo_despeje"], 0.05)
    d["factor_tratamiento"] = st.number_input("Factor del tratamiento químico (ρ tratada / ρ nativa) · supuesto",
                                              0.1, 1.0, DATOS["factor_tratamiento"], 0.05)
    d["resistencia_max"] = st.number_input("Rg máxima admitida (Ω)", 0.1, 25.0, DATOS["resistencia_max"], 0.1)
with st.sidebar.expander("Rayos y sombra (IEC 62305)"):
    d["densidad_rayos"] = st.number_input("Densidad de descargas Ng (rayos/km²/año)", 0.1, 60.0,
                                          DATOS["densidad_rayos"], 0.5)
    d["nivel_proteccion"] = st.selectbox("Nivel de protección", list(RADIO_ESFERA),
                                         index=list(RADIO_ESFERA).index(DATOS["nivel_proteccion"]))
    d["hora_inicio_sombra"], d["hora_fin_sombra"] = st.slider(
        "Horas sin sombra de mástiles sobre paneles (hora solar)", 6.0, 18.0,
        (DATOS["hora_inicio_sombra"], DATOS["hora_fin_sombra"]), 0.5)
    d["altura_paneles"] = st.number_input("Altura del borde superior de las mesas (m)", 0.5, 4.0,
                                          DATOS["altura_paneles"], 0.1)
kml_subido = st.sidebar.file_uploader("Otro terreno (KML de Google Earth)", type=["kml"])
texto_kml = kml_subido.getvalue().decode("utf-8") if kml_subido else (AQUI / "terreno.kml").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def proyecto(datos_json, kml):
    return Proyecto(kml, json.loads(datos_json))


@st.cache_data(show_spinner=False)
def resultado_guardado():
    f = AQUI / "resultados_base.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


datos_json = json.dumps(d, sort_keys=True)
proy = proyecto(datos_json, texto_kml)
base = resultado_guardado()
es_base = (base is not None and kml_subido is None
           and json.dumps(base["datos"], sort_keys=True) == datos_json)

if es_base:
    resultado = base
else:
    clave = "opt_" + str(hash((datos_json, texto_kml)))
    resultado = st.session_state.get(clave)
    if resultado is None:
        st.title("Planta FV 2 MW · SPT y pararrayos")
        st.warning("Cambiaste los datos de entrada. Hay que volver a optimizar malla y pararrayos "
                   "(tarda entre 2 y 6 minutos).")
        if st.button("Optimizar con estos datos", type="primary"):
            from precalcular import correr
            barra = st.progress(0.0, "Algoritmo genético (pymoo)…")
            _, resultado = correr(d, texto_kml, progreso=lambda f: barra.progress(min(f, 1.0), "Algoritmo genético (pymoo)…"))
            st.session_state[clave] = resultado
            st.rerun()
        st.stop()

h, filas, D2, modo, i_cond, mejora = resultado["x"]
grava, tratado = bool(mejora & 1), bool(mejora & 2)
D = D2 / 2
costo, disp, malla, pecar = proy.evaluar(h, filas, D, modo, i_cond, mejora)

# ------------------------------------------------------------------ encabezado
st.title("Planta fotovoltaica de 2 MW · Santa Fe de Antioquia")
st.caption("Sistema de puesta a tierra (IEEE Std 80-2013) y protección externa contra rayos "
           "(IEC 62305, esfera rodante; RETIE), optimizados juntos al menor costo que cumple la norma.")
n_mod = len(disp.mesas) * d["modulos_por_mesa"]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Potencia instalada", f"{n_mod * d['potencia_modulo_w'] / 1e6:.3f} MWp")
c2.metric("Mástiles", f"{len(disp.mastiles)} × {h} m")
c3.metric("Malla", f"D = {D:.1f} m · {malla['nR']} varillas")
c4.metric("Rg", f"{malla['Rg']:.3f} Ω")
c5.metric("Costo SPT + PECAR", f"${costo / 1e6:,.1f} M COP")

tabs = st.tabs(["0 · Datos", "1 · Terreno y paneles", "2 · Pararrayos y sombra", "3 · Malla IEEE 80",
                "4 · Optimización conjunta", "5 · Materiales y presupuesto"])

# ------------------------------------------------------------------ 0 datos
with tabs[0]:
    st.subheader("Datos de entrada fijados al inicio")
    st.write("Todos los cálculos parten de estos valores. Así no hay que rehacer el diseño a mitad de camino: "
             "si cambia un dato, se cambia aquí y la app vuelve a optimizar todo.")
    filas_datos = [
        ("Potencia objetivo", "2 MWp", "Especificación del proyecto"),
        ("Módulo", f"{d['potencia_modulo_w']} Wp, {d['largo_modulo']} × {d['ancho_modulo']} m", "Igual a la referencia"),
        ("Resistividad del suelo", f"{d['resistividad_suelo']:.0f} Ω·m nativa; con tratamiento {d['resistividad_suelo'] * d['factor_tratamiento']:.0f} Ω·m", "Supuesto: suelo aluvial seco del cañón del Cauca; tratamiento como en la referencia"),
        ("Corriente de malla IG / despeje", f"{d['corriente_falla']:.0f} A / {d['tiempo_despeje']} s", "Igual a la referencia (literatura, Sf = 1); confirmar con el operador de red"),
        ("Profundidad de malla / varilla", f"{d['profundidad_malla']} m / copperweld 5/8\" × {d['longitud_varilla']} m", "IEEE 80, comercial"),
        ("Densidad de descargas Ng", f"{d['densidad_rayos']} rayos/km²/año", "EPM, Anexo A parámetros meteorológicos: Olaya 11.4, Sopetrán y San Jerónimo 11"),
        ("Nivel de protección", f"{d['nivel_proteccion']} (esfera de {RADIO_ESFERA[d['nivel_proteccion']]:.0f} m)", "Igual a la referencia, IEC 62305-3"),
        ("Sombra", f"Sin sombra sobre paneles de {d['hora_inicio_sombra']:.1f} h a {d['hora_fin_sombra']:.1f} h, todo el año", "Criterio de diseño FV"),
        ("Pasillos", f"Entre filas {d['espacio_entre_filas']} m; principal ≥ {d['ancho_min_pasillo']} m", "RETIE 3.17.23 y NTC 2050 110.26 (≥ 0.76 m)"),
    ]
    st.dataframe(pd.DataFrame(filas_datos, columns=["Dato", "Valor", "Fuente / justificación"]),
                 hide_index=True, width="stretch")
    st.subheader("Supuestos que faltan por confirmar")
    st.dataframe(pd.DataFrame(SUPUESTOS_POR_CONFIRMAR, columns=["Dato", "Valor adoptado", "Quién lo confirma"]),
                 hide_index=True, width="stretch")
    st.subheader("Precios unitarios (COP)")
    precios = [("Cable de cobre desnudo", f"{1142.4:,.0f} por mm² y por metro", "Referencia (escalado por sección)")]
    precios += [("Varilla copperweld", f"{PRECIOS['varilla']:,}", "Referencia"),
                ("Soldadura exotérmica", f"{PRECIOS['soldadura']:,}", "Referencia"),
                ("Punta captadora", f"{PRECIOS['punta_captadora']:,}", "Referencia"),
                ("Poste de concreto 12 m, 510 kg", "824,900 (68,742 por metro)", "Homecenter Colombia, nov. 2026"),
                ("Poste sobre 12 m", f"{PRECIOS['poste_m_sobre_12']:,} por metro adicional", "Supuesto (+50 %)"),
                ("Mástil de captación galvanizado 2 m", f"{PRECIOS['mastil_captacion']:,}", "CYPE Colombia: 2,147,392 por 6 m"),
                ("Instalación del poste", f"{PRECIOS['cimentacion_mastil']:,}", "Supuesto, cotizar"),
                ("Grava (capa superficial)", f"{PRECIOS['grava_m3']:,} por m³", "Supuesto, cotizar"),
                ("Tratamiento químico (bentonita)", f"{PRECIOS['tratamiento_m']:,} por m de conductor y {PRECIOS['tratamiento_varilla']:,} por varilla", "Supuesto, cotizar")]
    st.dataframe(pd.DataFrame(precios, columns=["Ítem", "Precio", "Fuente"]), hide_index=True, width="stretch")

# ------------------------------------------------------------------ 1 terreno y paneles
with tabs[1]:
    a, b = st.columns([3, 2])
    with a:
        st.pyplot(gr.plano_paneles(proy.terreno, disp, proy.sub))
    with b:
        st.subheader("Terreno")
        st.write(f"Lote de **{proy.terreno.area / 1e4:.2f} ha** (perímetro {proy.terreno.length:.0f} m), "
                 f"a {math.hypot(*proy.sub):.0f} m de la subestación Santa Fe de Antioquia 110 kV.")
        st.subheader("Paneles")
        st.write(f"- {len(disp.mesas)} mesas de {d['modulos_por_mesa']} módulos = **{n_mod} módulos**")
        st.write(f"- {n_mod} × {d['potencia_modulo_w']} W = **{n_mod * d['potencia_modulo_w'] / 1e6:.4f} MWp**")
        st.write(f"- Filas E-O, {d['espacio_entre_filas']} m entre filas (≥ 0.76 m del RETIE)")
        st.write(f"- Un pasillo de **{disp.ancho_pasillo:.1f} m** cada {filas} filas. Ese ancho no es arbitrario: "
                 f"es lo que necesita un mástil de {h} m para que su sombra no toque las filas vecinas "
                 f"(ver paso 2). También sirve de vía de mantenimiento.")
        st.write(f"- Área de la planta (envolvente de mesas y caseta): {disp.planta.area / 1e4:.2f} ha")
        st.subheader("Caseta técnica")
        st.write(f"{d['caseta_ancho']} × {d['caseta_largo']} m, en el punto del lote más cercano a la subestación.")

# ------------------------------------------------------------------ 2 pararrayos
with tabs[2]:
    a, b = st.columns([3, 2])
    with a:
        ver_sombra = st.toggle("Mostrar la sombra posible de cada mástil", value=True)
        st.pyplot(gr.plano_pecar(proy.terreno, disp, proy.vec, pecar, ver_sombra))
    with b:
        R = RADIO_ESFERA[d["nivel_proteccion"]]
        st.subheader("Esfera rodante")
        st.latex(r"r(h_o)=\sqrt{h(2R-h)}-\sqrt{h_o(2R-h_o)}")
        st.write(f"R = {R:.0f} m (nivel {d['nivel_proteccion']}), h = {h} m:")
        st.write(f"- a la altura de los paneles ({d['altura_paneles']} m): **r = {disp.radio_paneles:.2f} m**")
        st.write(f"- a la altura de la caseta ({d['altura_caseta']} m): r = {disp.radio_caseta:.2f} m")
        st.write(f"- cobertura verificada: **{disp.cobertura:.1f} %** de los puntos de muestra de mesas y caseta")
        st.info("La referencia usó el radio a nivel del suelo. Aquí se usa el radio a la altura del objeto "
                "protegido, que es lo que pide el método y es más conservador.")
        st.subheader("Sombra como restricción")
        st.write(f"Se calcula la posición del sol cada 15 min, de {d['hora_inicio_sombra']:.1f} h a "
                 f"{d['hora_fin_sombra']:.1f} h, cada 4 días del año (latitud {d['latitud']}° N). "
                 f"Una posición de mástil solo es candidata si su sombra en todos esos instantes no toca ninguna mesa. "
                 f"Quedaron {disp.candidatos_validos} posiciones candidatas útiles; entre ellas se escoge el menor "
                 f"número de mástiles que cubre todo (cobertura voraz y poda de redundantes).")
        Ad = disp.planta.buffer(3 * d["altura_paneles"]).area
        Nd = d["densidad_rayos"] * Ad * 1e-6
        st.subheader("Frecuencia de descargas")
        st.write(f"Área equivalente de captura ≈ {Ad / 1e4:.2f} ha → N_d = Ng·A_d·10⁻⁶ = **{Nd:.3f} descargas/año** "
                 f"(una cada {1 / Nd:.1f} años). Eficiencia del nivel {d['nivel_proteccion']}: "
                 f"{EFICIENCIA_LPL[d['nivel_proteccion']] * 100:.0f} %.")

# ------------------------------------------------------------------ 3 malla
with tabs[3]:
    a, b = st.columns([3, 2])
    with a:
        st.pyplot(gr.plano_malla(proy.terreno, disp, malla, pecar))
    with b:
        st.subheader("Verificación IEEE Std 80-2013")
        ver = pd.DataFrame([
            ("Tensión de malla Em", f"{malla['Em']:.1f} V", f"≤ {malla['Et']:.1f} V (contacto, 70 kg)", malla["cumple_contacto"]),
            ("Tensión de paso Es", f"{malla['Es']:.1f} V", f"≤ {malla['Ep']:.1f} V (paso, 70 kg)", malla["cumple_paso"]),
            ("Resistencia Rg (Sverak)", f"{malla['Rg']:.3f} Ω", f"≤ {d['resistencia_max']} Ω", malla["cumple_rg"]),
            ("Sección del conductor", f"{malla['seccion']} mm²", f"≥ {malla['A_min']:.1f} mm² (Onderdonk e IEC 62305-3)", malla["cumple_seccion"]),
            ("GPR = IG·Rg", f"{malla['GPR']:.0f} V", "informativo", True),
        ], columns=["Magnitud", "Valor", "Límite", "Cumple"])
        st.dataframe(ver, hide_index=True, width="stretch")
        st.write(f"Conductor **{malla['conductor']}**, {malla['Lc']:.0f} m enterrados a {d['profundidad_malla']} m; "
                 f"{MODOS_VARILLA[modo]} ({malla['nR']}); capa de grava: {'sí' if grava else 'no'}; "
                 f"tratamiento químico: {'sí, ρ = %.0f Ω·m en la malla (nativa %.0f Ω·m en la superficie)' % (malla['rho'], malla['rho_nativa']) if tratado else 'no'}.")
        st.write(f"Factores: n = {malla['n']:.2f}, Km = {malla['Km']:.3f}, Ki = {malla['Ki']:.3f}, "
                 f"Ks = {malla['Ks']:.3f}, Kii = {malla['Kii']:.3f}, Lm = {malla['Lm']:.0f} m, Ls = {malla['Ls']:.0f} m.")
        margen = (malla["Et"] - malla["Em"]) / malla["Et"] * 100
        st.write(f"Margen en la tensión de malla: {margen:.1f} %. La norma no exige margen adicional; "
                 f"se elige la malla más barata que cumple.")
    st.subheader("Barrido del espaciamiento con la misma disposición, varillas y conductor")
    barrido = []
    for DD in np.arange(d["D_min"], d["D_max"] + 0.01, 0.5):
        _, _, m2, p2 = proy.evaluar(h, filas, float(DD), modo, i_cond, mejora)
        barrido.append(dict(D=DD, Em=m2["Em"], Es=m2["Es"], costo=m2["costo"]))
    st.pyplot(gr.curva_D(barrido, D, malla["Et"], malla["Ep"]))

# ------------------------------------------------------------------ 4 optimizacion
with tabs[4]:
    st.subheader("Malla y pararrayos optimizados juntos (pymoo, algoritmo genético)")
    st.write("Variables de decisión: altura del mástil, filas de mesas entre pasillos, espaciamiento D de la malla, "
             "disposición de varillas, calibre del conductor, capa de grava y tratamiento químico del suelo. Objetivo: **costo total de SPT + PECAR**. "
             "Restricciones: Em ≤ contacto tolerable, Es ≤ paso tolerable, Rg ≤ máximo, sección ≥ mínima, "
             "cobertura del 100 % y ninguna sombra de mástil sobre paneles (esta última ya está dentro de la "
             "ubicación de los mástiles).")
    st.write("Por qué van juntos: la altura del mástil fija el ancho de los pasillos (por la sombra), los pasillos "
             "cambian el área de la planta, y el área cambia la malla. Además, cada mástil se une a la malla, así que "
             "la malla cambia el cable de unión y las varillas del PECAR.")
    x = resultado["x"]
    st.write(f"Óptimo: h = {x[0]} m, {x[1]} filas entre pasillos, D = {x[2] / 2:.1f} m, {MODOS_VARILLA[x[3]]}, "
             f"{CONDUCTORES[x[4]][0]}, grava {'sí' if x[5] & 1 else 'no'}, tratamiento químico {'sí' if x[5] & 2 else 'no'} → **${resultado['costo'] / 1e6:,.1f} M COP**. "
             f"El resultado del GA se verifica con una búsqueda exhaustiva alrededor del óptimo.")
    tabla = resultado.get("alturas") or []
    if tabla:
        st.pyplot(gr.curva_alturas(tabla, x[0]))
        df = pd.DataFrame(tabla)
        df = df.rename(columns={"h": "Altura (m)", "filas": "Filas entre pasillos", "mastiles": "Mástiles",
                                "costo_spt": "SPT (COP)", "costo_pecar": "PECAR (COP)", "costo_total": "Total (COP)"})
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%,.0f") for c in
                                    ["SPT (COP)", "PECAR (COP)", "Total (COP)"]})
        st.caption("Cada fila es la mejor combinación para esa altura (barrido exhaustivo). Las alturas sin "
                   "valor no logran cubrir todo sin sombrear los paneles.")

# ------------------------------------------------------------------ 5 presupuesto
with tabs[5]:
    nombre, seccion, _ = CONDUCTORES[i_cond]
    filas_bom = [
        ("SPT", f"Cable Cu desnudo {nombre} (malla + anillo)", malla["Lc"], "m", malla["costo_cable"]),
        ("SPT", "Varilla copperweld 5/8\" × 2.4 m (malla)", malla["nR"], "u", malla["costo_varillas"]),
        ("SPT", "Soldadura exotérmica (cruces, extremos y varillas)", malla["soldaduras"], "u", malla["costo_soldaduras"]),
    ]
    if grava:
        filas_bom.append(("SPT", "Grava superficial", malla["A"] * d["espesor_grava"], "m³", malla["costo_grava"]))
    if tratado:
        filas_bom.append(("SPT", "Tratamiento químico del suelo (bentonita) en zanja", malla["Lc"], "m", malla["costo_tratamiento"]))
    unidades = {"Mastiles": (pecar["n"], "u"), "Puntas": (pecar["n"], "u"), "Bajantes": (pecar["L_bajante"], "m"),
                "Union": (pecar["L_union"], "m"), "Tubo": (pecar["n"] * 2, "m"), "Abrazaderas": (pecar["abrazaderas"], "u"),
                "Varillas": (len(pecar["varillas_pr"]), "u"), "Soldaduras": (pecar["soldaduras"], "u")}
    for item, valor in pecar["items"].items():
        cant, u = unidades[item.split()[0]]
        filas_bom.append(("PECAR", item, cant, u, valor))
    bom = pd.DataFrame(filas_bom, columns=["Sistema", "Ítem", "Cantidad", "Unidad", "Subtotal (COP)"])
    st.dataframe(bom, hide_index=True, width="stretch",
                 column_config={"Cantidad": st.column_config.NumberColumn(format="%.1f"),
                                "Subtotal (COP)": st.column_config.NumberColumn(format="%,.0f")})
    c1, c2, c3 = st.columns(3)
    c1.metric("SPT", f"${malla['costo'] / 1e6:,.1f} M")
    c2.metric("PECAR", f"${pecar['costo'] / 1e6:,.1f} M")
    c3.metric("Total", f"${costo / 1e6:,.1f} M COP")
    st.caption(f"Costo de un mástil de {h} m (poste de concreto + captación de 2 m) sin instalación: ${costo_mastil(h):,.0f}.")
    st.download_button("Descargar presupuesto (CSV)", bom.to_csv(index=False).encode("utf-8"),
                       "presupuesto_spt_pecar_2MW.csv", "text/csv")
