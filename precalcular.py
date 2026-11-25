"""Corre la optimizacion conjunta con los datos de datos.py y guarda el resultado
en resultados_base.json, para que la app abra al instante (Streamlit Cloud)."""
import json, time
from pathlib import Path
from datos import DATOS
from motor import Proyecto, optimizar, barrido_alturas

AQUI = Path(__file__).parent


def correr(datos=None, kml=None, progreso=None):
    d = dict(DATOS if datos is None else datos)
    texto = kml if kml is not None else (AQUI / "terreno.kml").read_text(encoding="utf-8")
    proy = Proyecto(texto, d)
    t = time.time()
    costo, x = optimizar(proy, progreso=progreso)
    tabla = barrido_alturas(proy, x)
    return proy, dict(datos=d, x=list(map(int, x)), costo=float(costo), alturas=tabla,
                      segundos=round(time.time() - t, 1))


if __name__ == "__main__":
    _, r = correr(progreso=lambda f: print(f"GA {f:5.0%}", flush=True))
    (AQUI / "resultados_base.json").write_text(json.dumps(r, indent=1, default=float), encoding="utf-8")
    print("optimo", r["x"], round(r["costo"] / 1e6, 1), "M COP en", r["segundos"], "s")
