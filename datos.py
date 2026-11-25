"""
PASO 0 - DATOS DE ENTRADA (se fijan ANTES de disenar).

Todo el diseno parte de este diccionario. La app de Streamlit permite
cambiarlos, pero el diseno base se calcula con estos valores. Cada dato
lleva su fuente o, si es un supuesto, su justificacion, para que no haya
que cambiarlo a mitad del trabajo.

Los valores marcados SUPUESTO deben confirmarse (medicion en campo,
operador de red o asesor) antes de la entrega final.
"""

DATOS = {
    # ---------------- Planta ----------------
    "potencia_objetivo_w": 2_000_000,      # 2 MWp (especificacion del proyecto)
    "potencia_modulo_w": 550,              # modulo comercial 550 Wp (igual que la referencia)
    "largo_modulo": 2.278,                 # m
    "ancho_modulo": 1.134,                 # m
    "modulos_por_mesa": 12,                # mesa de 12 modulos en vertical (13.6 m x 2.278 m)
    "espacio_entre_mesas": 0.3,            # m, en la misma fila
    "espacio_entre_filas": 1.3,            # m, >= 0.76 m (RETIE / NTC 2050 110.26)
    "retiro_borde": 3.0,                   # m, retiro perimetral del lote
    "min_mesas_por_tramo": 6,              # no se arrancan filas cortas en las puntas del lote
    "ancho_min_pasillo": 1.5,              # m, pasillo principal minimo (2 x 0.76 m del RETIE)
    "altura_paneles": 1.5,                 # m, borde superior de la mesa (objeto a proteger)
    "caseta_ancho": 6.0, "caseta_largo": 4.0, "altura_caseta": 3.0,   # inversores + BESS

    # ---------------- Suelo y falla (IEEE Std 80-2013) ----------------
    # SUPUESTO: Santa Fe de Antioquia esta en el canon del rio Cauca, clima
    # seco (bosque seco tropical), suelos aluviales arenoso-gravosos. Para ese
    # tipo de suelo la literatura da 100 a 1000 ohm-m; se adopta 300 ohm-m
    # (el doble de lo que uso la referencia en Barbosa) y SIN tratamiento
    # quimico, para no depender de un valor que despues haya que corregir.
    "resistividad_suelo": 300.0,           # ohm-m (SUPUESTO hasta tener medicion Wenner)
    # Igual que la referencia (2500 A, 0.5 s, valor de literatura, Sf = 1 conservador).
    # Confirmar con el estudio de cortocircuito del operador de red antes de construir.
    "corriente_falla": 2500.0,             # A, corriente maxima de malla IG
    "tiempo_despeje": 0.5,                 # s
    "profundidad_malla": 0.5,              # m
    "longitud_varilla": 2.4,               # m, copperweld 5/8" x 2.4 m
    "resistencia_max": 1.0,                # ohm, valor de referencia adoptado (mismo criterio de la referencia)
    "seccion_minima_mm2": 50.0,            # mm2, IEC 62305-3 tabla 7 (conductor de tierra de cobre)
    "resistividad_grava": 3000.0,          # ohm-m, capa superficial de grava (IEEE 80, valor tipico humedo)
    "espesor_grava": 0.10,                 # m
    # Tratamiento quimico (bentonita/GEM) alrededor de conductores y varillas, como en
    # la referencia (150 -> 75 ohm-m): la resistividad que ve la malla baja a la mitad.
    # SUPUESTO; confirmar con Wenner antes y despues del tratamiento.
    "factor_tratamiento": 0.5,

    # ---------------- Rayos (IEC 62305 / NTC 4552) ----------------
    # Densidad de descargas a tierra: EPM, Anexo A "Caracterizacion de los parametros
    # meteorologicos en las zonas de influencia del Grupo EPM" (EPM-UCET-NYL-GM-012).
    # Santa Fe de Antioquia no aparece; sus vecinos Sopetran y San Jeronimo tienen 11
    # y Olaya 11.4 rayos/km2-ano. Se adopta el mayor (11.4), conservador.
    "densidad_rayos": 11.4,                # rayos/km2/ano
    "nivel_proteccion": "III",             # LPL III, igual que la referencia (IEC 62305); esfera de 45 m
    # Sombra: ningun mastil puede sombrear un panel entre estas horas solares,
    # ningun dia del ano (criterio usual de diseno FV; la referencia solo
    # revisaba el 21 de diciembre a las 3 p.m.).
    "hora_inicio_sombra": 9.0,
    "hora_fin_sombra": 15.0,
    "latitud": 6.543,

    # ---------------- Busqueda (pymoo) ----------------
    "altura_min": 6, "altura_max": 20,     # m, alturas de mastil a probar
    "D_min": 5.0, "D_max": 60.0,           # m, espaciamiento de la malla
    "filas_min": 4, "filas_max": 20,       # filas de mesas entre pasillos de mastiles
}

RADIO_ESFERA = {"I": 20.0, "II": 30.0, "III": 45.0, "IV": 60.0}
EFICIENCIA_LPL = {"I": 0.98, "II": 0.95, "III": 0.90, "IV": 0.80}

# Precios unitarios (COP). Los que vienen de la referencia (precios de mercado
# colombiano consultados el 2026-10-04 por el grupo de Barbosa) se usan igual.
# Los cables se escalan por seccion con el precio por mm2 de la referencia
# (114 243 COP/m para 100 mm2 -> 1 142.4 COP por mm2 y por metro).
PRECIO_CU_MM2_M = 1142.4
CONDUCTORES = [  # (nombre, seccion mm2, diametro m)
    ("50 mm2 (1/0 AWG aprox.)", 50.0, 0.00798),
    ("2/0 AWG (67.4 mm2)", 67.4, 0.01051),
    ("4/0 AWG (107.2 mm2)", 107.2, 0.01341),
    ("250 kcmil (126.7 mm2)", 126.7, 0.01460),
]
PRECIOS = {
    "varilla": 64_900,              # u, copperweld 5/8" x 2.4 m (referencia)
    "soldadura": 37_325,            # u, exotermica (referencia)
    "punta_captadora": 119_833,     # u, Franklin 4 puntas (referencia)
    "tubo_pvc_m": 1_767,            # m, conduit PVC 3/4" (referencia)
    "cable_bajante_m": 50 * PRECIO_CU_MM2_M,   # 50 mm2 (referencia)
    # Mastil = poste de concreto (empotrado ~1.8 m) + mastil de captacion galvanizado de 2 m
    # en la cima, de modo que la punta queda a la altura h del poste.
    #  - Poste de concreto 12 m, 510 kg: 824 900 COP (Homecenter Colombia, nov. 2026)
    #    -> 68 742 COP por metro hasta 12 m.
    #  - Mastil de acero galvanizado 1 1/2": 2 147 392 COP por 6 m (CYPE, generador de
    #    precios Colombia) -> 357 899 COP/m -> 715 800 COP el tramo de 2 m.
    #  - Sobre 12 m: poste reforzado/autosoportado, +50 % por metro (SUPUESTO).
    #  - Instalacion con grua y empotramiento: 600 000 COP por poste (SUPUESTO, cotizar).
    "poste_m_hasta_12": 68_742,
    "poste_m_sobre_12": 103_100,
    "mastil_captacion": 715_800,
    "cimentacion_mastil": 600_000,
    "abrazadera": 8_000,            # u
    "grava_m3": 110_000,            # COP/m3 instalada
    # Tratamiento con bentonita sodica: zanja de ~0.10 x 0.10 m rellena (~12 kg/m),
    # bulto de 25 kg ~ 30 000 COP + mezcla y mano de obra -> ~20 000 COP por metro
    # de conductor y ~40 000 COP por varilla (perforacion rellena). SUPUESTO, cotizar.
    "tratamiento_m": 20_000,
    "tratamiento_varilla": 40_000,
}

SUPUESTOS_POR_CONFIRMAR = [
    ("Resistividad del suelo", "300 ohm-m", "Medicion Wenner en el lote o dato del asesor"),
    ("Corriente maxima de malla IG", "2 500 A, 0.5 s", "Operador de red (estudio de cortocircuito) o asesor"),
    ("Densidad de descargas Ng", "5 rayos/km2/ano", "Mapa NTC 4552-1 o Keraunos para Santa Fe de Antioquia"),
    ("Nivel de proteccion", "III (esfera de 45 m)", "Indicacion del asesor o analisis de riesgo IEC 62305-2"),
    ("Tratamiento del suelo", "rho a la mitad, 20 000 COP/m", "Wenner antes y despues; cotizacion de bentonita/GEM"),
    ("Precio de mastiles y grava", "ver tabla de precios", "Cotizacion (la referencia los dejo 'a cotizar')"),
]
