# SPT y pararrayos · Planta FV 2 MW · Santa Fe de Antioquia

App de Streamlit para el Seminario Integrador (Ingeniería Eléctrica, UdeA).
Diseña la puesta a tierra (IEEE Std 80-2013) y la protección externa contra
rayos (IEC 62305, esfera rodante; RETIE) de una planta FV hipotética de 2 MWp
en un lote de 4.3 ha cerca de la subestación Santa Fe de Antioquia 110 kV.

## Orden del diseño
0. **Datos de entrada fijos** (`datos.py`): resistividad, corriente de falla,
   densidad de rayos, nivel de protección, horas sin sombra y precios.
1. **Terreno, caseta y paneles con pasillos** (RETIE 3.17.23, NTC 2050 110.26).
2. **Sombra como restricción**: un mástil solo puede ir donde su sombra no toca
   ninguna mesa entre las horas fijadas, ningún día del año. Los pasillos se
   ensanchan para que quepan mástiles dentro del campo.
3. **Malla y pararrayos optimizados juntos** con pymoo (algoritmo genético):
   menor costo de SPT + PECAR que cumple IEEE 80 y cobertura del 100 %.

## Archivos
- `app.py`: la app (pestañas 0 a 5).
- `motor.py`: cálculos (terreno, sol, paneles, esfera rodante, IEEE 80, costos, pymoo).
- `datos.py`: datos de entrada, supuestos y precios.
- `graficas.py`: figuras.
- `precalcular.py`: corre la optimización y guarda `resultados_base.json`
  para que la app abra al instante. Volver a correrlo si se cambia `datos.py`.
- `terreno.kml`: polígono del lote.

## Correr en el computador
```
pip install -r requirements.txt
python precalcular.py      # solo si cambiaste datos.py (tarda unos minutos)
streamlit run app.py
```

## Publicar gratis (Streamlit Community Cloud)
1. Sube esta carpeta a un repositorio público de GitHub.
2. Entra a share.streamlit.io con tu cuenta de GitHub, "Create app",
   escoge el repositorio y `app.py` como archivo principal.
