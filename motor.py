"""
Motor de calculo: planta FV de 2 MW en Santa Fe de Antioquia.
SPT (IEEE Std 80-2013) + PECAR (IEC 62305, esfera rodante) optimizados juntos.

Orden del diseno (distinto al de la referencia de Barbosa):
  0. Datos de entrada fijos (datos.py).
  1. Terreno (KML -> UTM 18N), caseta y paneles con pasillos (RETIE).
  2. La sombra de los mastiles es una RESTRICCION desde que se ubican: solo
     se aceptan posiciones cuya sombra (todo el ano, entre las horas de
     produccion) no cae sobre ninguna mesa. Los pasillos se ensanchan lo
     necesario para que quepan mastiles dentro del campo sin sombrear.
  3. Malla y pararrayos se optimizan JUNTOS con pymoo (GA): se busca el
     menor costo de SPT + PECAR que cumpla IEEE 80 y cobertura del 100 %.
"""
import math
import re
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage
from shapely.geometry import Polygon, box, LineString, Point, MultiPoint
from shapely.ops import unary_union, nearest_points
from shapely import prepared

from datos import DATOS, RADIO_ESFERA, CONDUCTORES, PRECIOS, PRECIO_CU_MM2_M

SUBESTACION_LONLAT = (-75.8238173, 6.5505336)   # S/E Santa Fe de Antioquia 110 kV (OSM)
MODOS_VARILLA = ["sin varillas", "varillas en esquinas", "varillas en todo el perimetro"]


# ------------------------------------------------------------------ PASO 1: terreno
def utm18n(lon, lat):
    """Proyeccion UTM zona 18N (formulas de Snyder), igual a la referencia."""
    a = 6378137.0; f = 1 / 298.257223563; e2 = f * (2 - f); ep2 = e2 / (1 - e2); k0 = 0.9996
    phi, lam, lam0 = math.radians(lat), math.radians(lon), math.radians(-75.0)
    N = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    T = math.tan(phi) ** 2; C = ep2 * math.cos(phi) ** 2; A = (lam - lam0) * math.cos(phi)
    M = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T ** 2 + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000
    y = k0 * (M + N * math.tan(phi) * (A ** 2 / 2 + (5 - T + 9 * C + 4 * C ** 2) * A ** 4 / 24
              + (61 - 58 * T + T ** 2 + 600 * C - 330 * ep2) * A ** 6 / 720))
    return x, y


def leer_terreno(texto_kml):
    """Devuelve (poligono en metros relativos, punto de la subestacion en el mismo sistema)."""
    m = re.search(r"<Polygon>.*?<coordinates>(.*?)</coordinates>", texto_kml, re.DOTALL)
    pts = []
    for tok in m.group(1).split():
        lon, lat, *_ = tok.split(",")
        pts.append((float(lon), float(lat)))
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    xy = [utm18n(lo, la) for lo, la in pts]
    x0, y0 = min(p[0] for p in xy), min(p[1] for p in xy)
    terreno = Polygon([(x - x0, y - y0) for x, y in xy])
    sx, sy = utm18n(*SUBESTACION_LONLAT)
    return terreno, (sx - x0, sy - y0)


# ------------------------------------------------------------------ sol y sombra
def vectores_sombra(lat, h_ini, h_fin, paso_dias=4, paso_h=0.25):
    """Desplazamiento (dx, dy) de la punta de la sombra de un objeto de 1 m de alto,
    para todos los dias del ano entre h_ini y h_fin (hora solar). Este = +x, Norte = +y."""
    phi = math.radians(lat)
    vec = []
    for n in range(1, 366, paso_dias):
        d = math.radians(23.45 * math.sin(math.radians(360 / 365 * (284 + n))))
        for t in np.arange(h_ini, h_fin + 1e-9, paso_h):
            w = math.radians(15 * (t - 12))
            el = math.asin(math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.cos(w))
            if el <= math.radians(5):
                continue
            az = math.atan2(-math.cos(d) * math.sin(w),
                            math.sin(d) * math.cos(phi) - math.cos(d) * math.sin(phi) * math.cos(w))
            vec.append((-math.sin(az) / math.tan(el), -math.cos(az) / math.tan(el)))
    return np.array(vec)


def huella_sombra(vec):
    """Huella de la sombra de un mastil de 1 m (envolvente convexa del pie y de todas las puntas)."""
    return MultiPoint([(0.0, 0.0)] + [tuple(v) for v in vec]).convex_hull


def ancho_pasillo_mastil(h, vec, ancho_min, holgura=2.0):
    """Pasillo E-O en el que cabe un mastil de altura h sin sombrear las filas vecinas."""
    alcance_n = max(0.0, vec[:, 1].max()) * h
    alcance_s = max(0.0, -vec[:, 1].min()) * h
    return max(ancho_min, alcance_n + alcance_s + 2 * holgura), alcance_s + holgura


# ------------------------------------------------------------------ PASO 1b: caseta y paneles
def ubicar_caseta(terreno, sub_xy, d):
    """Caseta en el punto del area util mas cercano a la subestacion de 110 kV."""
    util = terreno.buffer(-d["retiro_borde"])
    p = nearest_points(util, Point(sub_xy))[0]
    a, b = d["caseta_ancho"], d["caseta_largo"]
    for paso in np.arange(0, 60, 1.0):
        cx, cy = util.centroid.x, util.centroid.y
        t = paso / max(1e-9, Point(p).distance(Point(cx, cy)))
        qx, qy = p.x + (cx - p.x) * t, p.y + (cy - p.y) * t
        c = box(qx - a / 2, qy - b / 2, qx + a / 2, qy + b / 2)
        if util.contains(c):
            return c
    raise ValueError("No cabe la caseta")


def distribuir_paneles(terreno, caseta, d, filas_por_bloque, ancho_pasillo):
    """Filas E-O de norte a sur (la subestacion esta al noroccidente). Cada
    `filas_por_bloque` filas se deja un pasillo de `ancho_pasillo` (para
    mantenimiento y para los mastiles). Se ubican mesas hasta llegar a 2 MW."""
    util = terreno.buffer(-d["retiro_borde"])
    util_p = prepared.prep(util)
    lote_p = prepared.prep(terreno.buffer(-0.5))
    zona_caseta = caseta.buffer(3.0)
    largo = d["modulos_por_mesa"] * d["ancho_modulo"]
    ancho = d["largo_modulo"]
    n_mesas = math.ceil(d["potencia_objetivo_w"] / (d["potencia_modulo_w"] * d["modulos_por_mesa"]))
    xmin, ymin, xmax, ymax = util.bounds
    mesas, pasillos = [], []
    y_top, fila = ymax, 0
    while y_top - ancho >= ymin and len(mesas) < n_mesas:
        yc = y_top - ancho / 2
        linea = LineString([(xmin - 5, yc), (xmax + 5, yc)]).intersection(util)
        segs = [linea] if linea.geom_type == "LineString" else list(getattr(linea, "geoms", []))
        tramos = [s for s in segs if not s.is_empty and s.length >= d["min_mesas_por_tramo"] * (largo + d["espacio_entre_mesas"])]
        if not tramos and not mesas:      # filas cortas en las puntas del lote: se dejan libres para mastiles
            y_top -= ancho + d["espacio_entre_filas"]
            continue
        for s in sorted(tramos, key=lambda g: g.bounds[0]):
            x = s.bounds[0]
            while x + largo <= s.bounds[2] and len(mesas) < n_mesas:
                m = box(x, y_top - ancho, x + largo, y_top)
                # primer bloque: debe quedar libre una franja al norte para los mastiles
                franja_ok = fila >= filas_por_bloque or lote_p.contains(box(x, y_top - ancho, x + largo, y_top + ancho_pasillo))
                if util_p.contains(m) and not m.intersects(zona_caseta) and franja_ok:
                    mesas.append(m)
                x += largo + d["espacio_entre_mesas"]
        fila += 1
        if fila % filas_por_bloque == 0:
            pasillos.append((y_top - ancho - ancho_pasillo, y_top - ancho))
            y_top -= ancho + ancho_pasillo
        else:
            y_top -= ancho + d["espacio_entre_filas"]
    return mesas, pasillos, n_mesas


# ------------------------------------------------------------------ PASO 2: pararrayos
def radio_proteccion(h, ho, R):
    """Radio protegido a la altura ho por un mastil de altura h (esfera rodante de radio R)."""
    h = min(h, R)
    ho = min(ho, h)
    return math.sqrt(h * (2 * R - h)) - math.sqrt(ho * (2 * R - ho))


def puntos_muestra(geoms, paso=1.5):
    pts = []
    for g in geoms:
        x0, y0, x1, y1 = g.bounds
        nx = max(2, int(math.ceil((x1 - x0) / paso)) + 1)
        for yy in (y0, (y0 + y1) / 2, y1):
            for xx in np.linspace(x0, x1, nx):
                pts.append((xx, yy))
    return np.array(pts)


@dataclass
class Disposicion:
    h: int
    filas: int
    ancho_pasillo: float
    mesas: list
    pasillos: list
    caseta: object
    planta: object
    mastiles: np.ndarray = None
    radio_paneles: float = 0.0
    radio_caseta: float = 0.0
    cobertura: float = 0.0
    factible: bool = False
    motivo: str = ""
    candidatos_validos: int = 0
    cables: list = field(default_factory=list)


def disenar_pecar(terreno, caseta, mesas, h, d, vec, res=0.5):
    """Mastiles: candidatos en una cuadricula de 2 m dentro del lote, se descartan los
    que sombrean alguna mesa (restriccion de sombra) y se cubre con el menor numero
    (cobertura voraz + poda de redundantes)."""
    R = RADIO_ESFERA[d["nivel_proteccion"]]
    rp = radio_proteccion(h, d["altura_paneles"], R)
    rc = radio_proteccion(h, d["altura_caseta"], R)
    xmin, ymin, xmax, ymax = terreno.bounds
    nx, ny = int((xmax - xmin) / res) + 3, int((ymax - ymin) / res) + 3
    ocup = np.zeros((ny, nx), bool)
    for m in mesas:
        a, b, c, e = m.bounds
        ocup[int((b - ymin) / res):int((e - ymin) / res) + 1, int((a - xmin) / res):int((c - xmin) / res) + 1] = True
    # nucleo = huella de la sombra reflejada + 1 m de holgura alrededor del mastil
    huella = huella_sombra(vec * h).buffer(0.5)
    hx0, hy0, hx1, hy1 = huella.bounds
    kx = np.arange(math.floor(hx0 / res), math.ceil(hx1 / res) + 1)
    ky = np.arange(math.floor(hy0 / res), math.ceil(hy1 / res) + 1)
    hp = prepared.prep(huella)
    ker = np.array([[hp.contains(Point(i * res, j * res)) for i in kx] for j in ky])
    # un mastil en p esta prohibido si p + huella toca una mesa:
    # prohibido[i, j] = OR sobre (a, b) de la huella de ocup[i + a, j + b]  (correlacion)
    from scipy import signal
    pt, pb, pl, pr = -ky.min(), ky.max(), -kx.min(), kx.max()
    pad = np.pad(ocup.astype(float), ((pt, pb), (pl, pr)))
    prohibido = signal.correlate(pad, ker.astype(float), mode="valid", method="fft") > 0.5
    zona = terreno.buffer(-0.5)
    zp = prepared.prep(zona)
    gx = np.arange(xmin + 1, xmax, 2.0)
    gy = np.arange(ymin + 1, ymax, 2.0)
    cand = []
    for yy in gy:
        for xx in gx:
            if prohibido[int(round((yy - ymin) / res)), int(round((xx - xmin) / res))]:
                continue
            if zp.contains(Point(xx, yy)):
                cand.append((xx, yy))
    cand = np.array(cand)
    sp = puntos_muestra(mesas)
    sc = puntos_muestra([caseta], paso=1.0)
    S = np.vstack([sp, sc])
    rad = np.r_[np.full(len(sp), rp), np.full(len(sc), rc)]
    if len(cand) == 0:
        return None, rp, rc, 0.0, "no hay posiciones sin sombra", 0
    if d.get("cables_guarda"):
        return pecar_con_cables(cand, S, rad, h, d, R, rp, rc)
    # solo candidatos que alcanzan a cubrir algo
    cov = np.zeros((len(cand), len(S)), bool)
    for i in range(0, len(cand), 800):
        c = cand[i:i + 800]
        dd = np.hypot(c[:, None, 0] - S[None, :, 0], c[:, None, 1] - S[None, :, 1])
        cov[i:i + 800] = dd <= rad[None, :]
    util = cov.any(1)
    cand, cov = cand[util], cov[util]
    cubrible = cov.any(0)
    if not cubrible.all():
        frac = cubrible.mean() * 100
        disenar_pecar.ultimos_no_cubiertos = S[~cubrible]
        return None, rp, rc, frac, f"{(~cubrible).sum()} puntos de las mesas no se pueden cubrir sin sombrear", len(cand)
    # cobertura voraz
    falta = np.ones(len(S), bool)
    elegidos = []
    while falta.any():
        gan = cov[:, falta].sum(1)
        k = int(gan.argmax())
        elegidos.append(k)
        falta &= ~cov[k]
    # poda de redundantes
    cambio = True
    while cambio:
        cambio = False
        for k in sorted(elegidos, key=lambda k: cov[k].sum()):
            resto = [j for j in elegidos if j != k]
            if resto and cov[resto].any(0).all():
                elegidos = resto
                cambio = True
                break
    return (cand[elegidos], []), rp, rc, 100.0, "", len(cand)


def costo_unitario_mastil(h, d):
    p = PRECIOS
    return (costo_mastil(h) + p["cimentacion_mastil"] + p["punta_captadora"]
            + (h + d["profundidad_malla"]) * p["cable_bajante_m"] + 2 * p["tubo_pvc_m"]
            + math.ceil(h - 2) * p["abrazadera"] + 3 * p["soldadura"])


def pecar_con_cables(cand, S, rad, h, d, R, rp, rc):
    """Cables de guarda (IEC 62305-3, conductores tendidos) entre mastiles a lo largo de
    los pasillos. Un cable horizontal a la altura h - flecha protege la franja a menos de
    r(h - flecha, ho) de su eje; la sombra de un cable de 9 mm se desprecia. Se escogen
    cables y mastiles sueltos con un algoritmo voraz por costo (cobertura / costo)."""
    vano = d["vano_max"]
    flecha = 0.02 * vano                                # ~2 % del vano
    hw = h - flecha
    ho_p, ho_c = d["altura_paneles"], d["altura_caseta"]
    rad_w = np.where(rad == rp, radio_proteccion(hw, ho_p, R), radio_proteccion(hw, ho_c, R))
    Cm = costo_unitario_mastil(h, d)
    Cw = PRECIOS["cable_bajante_m"]
    # tramos candidatos: corridas de posiciones permitidas consecutivas en una misma fila (paso 2 m)
    tramos = []
    for y in np.unique(cand[:, 1]):
        xs = np.sort(cand[cand[:, 1] == y, 0])
        ini = xs[0]
        for a, b in zip(xs, np.r_[xs[1:], np.inf]):
            if b - a > 2.01:
                if a - ini >= 30:
                    tramos.append((ini, a, y))
                ini = b
    cov_m = np.zeros((len(cand), len(S)), bool)
    for i in range(0, len(cand), 800):
        c = cand[i:i + 800]
        cov_m[i:i + 800] = np.hypot(c[:, None, 0] - S[None, :, 0], c[:, None, 1] - S[None, :, 1]) <= rad[None, :]

    def completar_con_mastiles(falta):
        elegidos = []
        while falta.any():
            g = cov_m[:, falta].sum(1)
            k = int(g.argmax())
            if g[k] == 0:
                return None
            elegidos.append(k)
            falta = falta & ~cov_m[k]
        return elegidos

    def solucion(umbral):
        """Fase 1: cables (voraz por cobertura/costo) mientras rindan >= umbral x el mejor
        cable; fase 2: mastiles sueltos para lo que falte."""
        falta = np.ones(len(S), bool)
        cables, mast_c, r0 = [], [], None
        while falta.any() and umbral is not None:
            mejor = None
            Sx, Sy, rw = S[falta, 0], S[falta, 1], rad_w[falta]
            idx = np.where(falta)[0]
            for (x0, x1, y) in tramos:
                ok = np.hypot(np.clip(Sx, x0, x1) - Sx, Sy - y) <= rw
                if not ok.any():
                    continue
                xs = Sx[ok]
                a = max(x0, x0 + np.floor((xs.min() - x0) / 2) * 2)
                b = min(x1, x0 + np.ceil((xs.max() - x0) / 2) * 2)
                if b - a < 10:
                    continue
                costo = (math.ceil((b - a) / vano) + 1) * Cm + (b - a) * Cw
                if mejor is None or ok.sum() / costo > mejor[0]:
                    mejor = (ok.sum() / costo, (a, b, y), idx[ok])
            if mejor is None:
                break
            r0 = r0 or mejor[0]
            if mejor[0] < umbral * r0:
                break
            a, b, y = mejor[1]
            n = math.ceil((b - a) / vano)
            cables.append((a, b, y))
            mast_c += [(a + (b - a) * j / n, y) for j in range(n + 1)]
            falta[mejor[2]] = False
        el = completar_con_mastiles(falta.copy())
        if el is None:
            return None
        # poda de mastiles sueltos redundantes
        cubierto_c = ~falta
        cambio = True
        while cambio:
            cambio = False
            for k in sorted(el, key=lambda k: cov_m[k].sum()):
                resto = [j for j in el if j != k]
                if (cubierto_c | (cov_m[resto].any(0) if resto else False)).all():
                    el, cambio = resto, True
                    break
        mast = mast_c + [tuple(cand[k]) for k in el]
        L = sum(b - a for a, b, _ in cables)
        return len(mast) * Cm + L * Cw, np.array(mast), cables

    sols = [x for x in (solucion(u) for u in (None, 0.4, 0.7)) if x is not None]
    if not sols:
        return None, rp, rc, 0.0, "no se puede cubrir todo sin sombrear", len(cand)
    _, mastiles, cables = min(sols, key=lambda t: t[0])
    return (np.array(mastiles), cables), rp, rc, 100.0, "", len(cand)


# ------------------------------------------------------------------ PASO 3: malla (IEEE 80-2013)
def poligono_planta(mesas, caseta):
    return unary_union(mesas + [caseta]).convex_hull.buffer(1.0, join_style=2)


def geometria_malla(planta, D, modo_varillas, Lr):
    """Conductores paralelos a x y a y cada D (centrados en la planta), anillo perimetral y varillas."""
    xmin, ymin, xmax, ymax = planta.bounds
    def posiciones(a, b):
        n = max(1, int(math.floor((b - a) / D)))
        off = (b - a - n * D) / 2
        return [a + off + i * D for i in range(n + 1)]
    segs = []
    for x in posiciones(xmin, xmax):
        g = LineString([(x, ymin - 1), (x, ymax + 1)]).intersection(planta)
        segs += [g] if g.geom_type == "LineString" else [s for s in getattr(g, "geoms", []) if s.length > 0]
    for y in posiciones(ymin, ymax):
        g = LineString([(xmin - 1, y), (xmax + 1, y)]).intersection(planta)
        segs += [g] if g.geom_type == "LineString" else [s for s in getattr(g, "geoms", []) if s.length > 0]
    segs = [s for s in segs if s.length > 0.5]
    anillo = LineString(planta.exterior.coords)
    Lc = sum(s.length for s in segs) + anillo.length
    xs = posiciones(xmin, xmax); ys = posiciones(ymin, ymax)
    pp = prepared.prep(planta.buffer(-0.01))
    cruces = [(x, y) for x in xs for y in ys if pp.contains(Point(x, y))]
    extremos = []
    for s in segs:
        extremos += [s.coords[0], s.coords[-1]]
    esquinas = list(planta.exterior.coords)[:-1]
    if modo_varillas == 0:
        varillas = []
    elif modo_varillas == 1:
        varillas = esquinas
    else:
        varillas = esquinas + [e for e in extremos if min(math.dist(e, q) for q in esquinas) > 2 * Lr]
    return dict(segmentos=segs, anillo=anillo, Lc=Lc, cruces=cruces, extremos=extremos, varillas=varillas)


def disenar_malla(planta, D, modo_varillas, i_cond, mejora, d, geo=None):
    """mejora: 0 nada, 1 grava superficial, 2 tratamiento quimico, 3 grava + tratamiento."""
    grava, tratado = bool(mejora & 1), bool(mejora & 2)
    rho_nativa = d["resistividad_suelo"]
    # El tratamiento (bentonita/GEM alrededor de conductor y varillas) baja la resistividad
    # que ve la malla (Rg, Em, Es); la superficie que pisa la persona sigue siendo suelo nativo.
    rho = rho_nativa * (d["factor_tratamiento"] if tratado else 1.0)
    IG = d["corriente_falla"]; ts = d["tiempo_despeje"]
    hm = d["profundidad_malla"]; Lr = d["longitud_varilla"]
    nombre, seccion, diam = CONDUCTORES[i_cond]
    if geo is None:
        geo = geometria_malla(planta, D, modo_varillas, Lr)
    segs, anillo, Lc, cruces, extremos, varillas = (geo[k] for k in
        ("segmentos", "anillo", "Lc", "cruces", "extremos", "varillas"))
    xmin, ymin, xmax, ymax = planta.bounds
    Lx, Ly = xmax - xmin, ymax - ymin
    A, Lp = planta.area, planta.length
    nR = len(varillas); LR = nR * Lr
    LT = Lc + LR
    # IEEE 80-2013
    na = 2 * Lc / Lp
    nb = math.sqrt(Lp / (4 * math.sqrt(A)))
    nc = (Lx * Ly / A) ** (0.7 * A / (Lx * Ly))
    n = na * nb * nc
    Kh = math.sqrt(1 + hm / 1.0)
    Kii = 1.0 if nR > 0 else 1 / (2 * n) ** (2 / n)
    Km = (1 / (2 * math.pi)) * (math.log(D ** 2 / (16 * hm * diam) + (D + 2 * hm) ** 2 / (8 * D * diam) - hm / (4 * diam))
                                + (Kii / Kh) * math.log(8 / (math.pi * (2 * n - 1))))
    Ki = 0.644 + 0.148 * n
    Ks = (1 / math.pi) * (1 / (2 * hm) + 1 / (D + hm) + (1 / D) * (1 - 0.5 ** (n - 2)))
    if nR > 0:
        Lm = Lc + (1.55 + 1.22 * (Lr / math.sqrt(Lx ** 2 + Ly ** 2))) * LR
    else:
        Lm = Lc
    Ls = 0.75 * Lc + 0.85 * LR
    Em = rho * Km * Ki * IG / Lm
    Es = rho * Ks * Ki * IG / Ls
    Rg = rho * (1 / LT + 1 / math.sqrt(20 * A) * (1 + 1 / (1 + hm * math.sqrt(20 / A))))
    # tensiones tolerables, persona de 70 kg
    if grava:
        rs, hs = d["resistividad_grava"], d["espesor_grava"]
        Cs = 1 - 0.09 * (1 - rho_nativa / rs) / (2 * hs + 0.09)
    else:
        rs, Cs = rho_nativa, 1.0
    Et = (1000 + 1.5 * Cs * rs) * 0.157 / math.sqrt(ts)
    Ep = (1000 + 6.0 * Cs * rs) * 0.157 / math.sqrt(ts)
    # calibre minimo por corriente (Onderdonk, cobre recocido, Kf = 7.06)
    A_kcmil = IG / 1000 * 7.06 * math.sqrt(ts)
    A_min = max(A_kcmil * 0.5067, d["seccion_minima_mm2"])
    costo_cable = Lc * seccion * PRECIO_CU_MM2_M
    costo_var = nR * PRECIOS["varilla"]
    soldaduras = len(cruces) + len(extremos) + nR
    costo_sold = soldaduras * PRECIOS["soldadura"]
    costo_grava = A * d["espesor_grava"] * PRECIOS["grava_m3"] if grava else 0.0
    costo_trat = (Lc * PRECIOS["tratamiento_m"] + nR * PRECIOS["tratamiento_varilla"]) if tratado else 0.0
    return dict(D=D, modo=modo_varillas, conductor=nombre, seccion=seccion, grava=grava, tratado=tratado,
                rho=rho, rho_nativa=rho_nativa, costo_tratamiento=costo_trat,
                segmentos=segs, anillo=anillo, cruces=cruces, varillas=varillas, nR=nR,
                Lc=Lc, LR=LR, LT=LT, A=A, Lp=Lp, n=n, Kii=Kii, Km=Km, Ki=Ki, Ks=Ks, Lm=Lm, Ls=Ls,
                Em=Em, Es=Es, Rg=Rg, GPR=IG * Rg, Cs=Cs, Et=Et, Ep=Ep, A_min=A_min, soldaduras=soldaduras,
                costo_cable=costo_cable, costo_varillas=costo_var, costo_soldaduras=costo_sold,
                costo_grava=costo_grava, costo=costo_cable + costo_var + costo_sold + costo_grava + costo_trat,
                cumple_contacto=Em <= Et, cumple_paso=Es <= Ep, cumple_rg=Rg <= d["resistencia_max"],
                cumple_seccion=seccion >= A_min)


# ------------------------------------------------------------------ costo del PECAR
def costo_mastil(h):
    """Poste de concreto de longitud h + mastil de captacion de 2 m (sin instalacion)."""
    p = PRECIOS
    poste = min(h, 12) * p["poste_m_hasta_12"] + max(0, h - 12) * p["poste_m_sobre_12"]
    return poste + p["mastil_captacion"]


def costear_pecar(mastiles, h, malla, d, cables=()):
    p = PRECIOS; Lr = d["longitud_varilla"]
    red = unary_union(malla["segmentos"] + [malla["anillo"]])
    n = len(mastiles)
    uniones, varillas_pr = [], []
    ocupadas = [tuple(v) for v in malla["varillas"]]
    for m in mastiles:
        q = nearest_points(red, Point(m))[0]
        uniones.append((tuple(m), (q.x, q.y)))
        if all(math.dist(m, v) >= 2 * Lr for v in ocupadas):
            varillas_pr.append(tuple(m)); ocupadas.append(tuple(m))
    L_union = sum(math.dist(a, b) for a, b in uniones)
    L_bajante = n * (h + d["profundidad_malla"])
    abraz = n * math.ceil(h - 2)
    sold = 2 * n + len(varillas_pr)
    items = {
        "Mastiles (poste de concreto h = %d m + captacion) e instalacion" % h: n * (costo_mastil(h) + p["cimentacion_mastil"]),
        "Puntas captadoras": n * p["punta_captadora"],
        "Bajantes Cu 50 mm2": L_bajante * p["cable_bajante_m"],
        "Union enterrada mastil-malla Cu 50 mm2": L_union * p["cable_bajante_m"],
        "Tubo PVC de proteccion (0-2 m)": n * 2 * p["tubo_pvc_m"],
        "Abrazaderas": abraz * p["abrazadera"],
        "Varillas al pie de los mastiles": len(varillas_pr) * p["varilla"],
        "Soldaduras del PECAR": sold * p["soldadura"],
    }
    L_cables = sum(b - a for a, b, _ in cables)
    if cables:
        items["Cables de guarda Cu 50 mm2"] = L_cables * p["cable_bajante_m"]
        items["Herrajes de amarre y suspension"] = sum(math.ceil((b - a) / d["vano_max"]) + 1 for a, b, _ in cables) * p["herraje_cable"]
    return dict(n=n, cables=list(cables), L_cables=L_cables, uniones=uniones, varillas_pr=varillas_pr, L_union=L_union, L_bajante=L_bajante,
                abrazaderas=abraz, soldaduras=sold, items=items, costo=sum(items.values()))


# ------------------------------------------------------------------ problema conjunto
class Proyecto:
    def __init__(self, texto_kml, d=None):
        self.d = dict(DATOS if d is None else d)
        self.terreno, self.sub = leer_terreno(texto_kml)
        self.vec = vectores_sombra(self.d["latitud"], self.d["hora_inicio_sombra"], self.d["hora_fin_sombra"])
        self.caseta = ubicar_caseta(self.terreno, self.sub, self.d)
        self._cache = {}
        self._geo = {}

    def disposicion(self, h, filas):
        key = (int(h), int(filas))
        if key in self._cache:
            return self._cache[key]
        d = self.d
        ancho, _ = ancho_pasillo_mastil(h, self.vec, d["ancho_min_pasillo"])
        mesas, pasillos, n_obj = distribuir_paneles(self.terreno, self.caseta, d, filas, ancho)
        disp = Disposicion(h=int(h), filas=int(filas), ancho_pasillo=ancho, mesas=mesas, pasillos=pasillos,
                           caseta=self.caseta, planta=None)
        if len(mesas) < n_obj:
            disp.motivo = f"solo caben {len(mesas)} de {n_obj} mesas"
        else:
            disp.planta = poligono_planta(mesas, self.caseta)
            m, rp, rc, cob, motivo, nc = disenar_pecar(self.terreno, self.caseta, mesas, h, d, self.vec)
            disp.radio_paneles, disp.radio_caseta, disp.cobertura = rp, rc, cob
            disp.candidatos_validos = nc
            disp.motivo = motivo
            disp.factible = m is not None
            if m is not None:
                disp.mastiles, disp.cables = m
        self._cache[key] = disp
        return disp

    def evaluar(self, h, filas, D, modo, i_cond, grava):
        disp = self.disposicion(h, filas)
        if not disp.factible:
            return None, disp, None, None
        kg = (int(h), int(filas), float(D), int(modo))
        if kg not in self._geo:
            self._geo[kg] = geometria_malla(disp.planta, D, modo, self.d["longitud_varilla"])
        malla = disenar_malla(disp.planta, D, modo, i_cond, grava, self.d, self._geo[kg])
        pecar = costear_pecar(disp.mastiles, h, malla, self.d, disp.cables)
        return malla["costo"] + pecar["costo"], disp, malla, pecar


def optimizar(proy, pop=30, gens=30, semilla=1, progreso=None):
    """GA de pymoo sobre variables enteras:
    x = [h (m), filas entre pasillos, 2*D (m), modo de varillas, conductor, mejora del suelo (0 nada, 1 grava, 2 tratamiento, 3 ambos)]."""
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.algorithms.soo.nonconvex.ga import GA
    from pymoo.operators.sampling.rnd import IntegerRandomSampling
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PM
    from pymoo.operators.repair.rounding import RoundingRepair
    from pymoo.optimize import minimize
    from pymoo.core.callback import Callback

    d = proy.d
    xl = np.array([d["altura_min"], d["filas_min"], int(2 * d["D_min"]), 0, 0, 0])
    xu = np.array([d["altura_max"], d["filas_max"], int(2 * d["D_max"]), 2, len(CONDUCTORES) - 1, 3])
    PEN = 1e10

    class Problema(ElementwiseProblem):
        def __init__(self):
            super().__init__(n_var=6, n_obj=1, n_ieq_constr=5, xl=xl, xu=xu, vtype=int)

        def _evaluate(self, x, out, *args, **kw):
            h, f, D2, modo, ic, gr = [int(round(v)) for v in x]
            costo, disp, malla, pecar = proy.evaluar(h, f, D2 / 2, modo, ic, gr)
            if costo is None:
                out["F"] = [PEN]; out["G"] = [1, 1, 1, 1, 1]; return
            out["F"] = [costo]
            out["G"] = [(malla["Em"] - malla["Et"]) / malla["Et"],
                        (malla["Es"] - malla["Ep"]) / malla["Ep"],
                        (malla["Rg"] - d["resistencia_max"]) / d["resistencia_max"],
                        (malla["A_min"] - malla["seccion"]) / malla["A_min"],
                        (100.0 - disp.cobertura) / 100]

    class Avance(Callback):
        def notify(self, algorithm):
            if progreso:
                progreso(algorithm.n_gen / gens)

    alg = GA(pop_size=pop, sampling=IntegerRandomSampling(),
             crossover=SBX(prob=0.9, eta=3.0, vtype=float, repair=RoundingRepair()),
             mutation=PM(eta=3.0, vtype=float, repair=RoundingRepair()),
             eliminate_duplicates=True)
    res = minimize(Problema(), alg, ("n_gen", gens), seed=semilla, callback=Avance(), verbose=False)
    h, f, D2, modo, ic, gr = [int(round(v)) for v in np.atleast_1d(res.X)]
    # verificacion local exhaustiva alrededor del optimo del GA (h y filas +-1, todo D, modo, conductor y grava)
    mejor = (res.F[0], (h, f, D2, modo, ic, gr))
    for hh in range(max(d["altura_min"], h - 1), min(d["altura_max"], h + 1) + 1):
        for ff in range(max(d["filas_min"], f - 1), min(d["filas_max"], f + 1) + 1):
            if not proy.disposicion(hh, ff).factible:
                continue
            for mm in range(3):
                for DD2 in range(int(2 * d["D_min"]), int(2 * d["D_max"]) + 1, 1 if (hh, ff) == (h, f) else 4):
                    for ii in range(len(CONDUCTORES)):
                        for gg in range(4):
                            c, disp, ma, pe = proy.evaluar(hh, ff, DD2 / 2, mm, ii, gg)
                            if c is None or c >= mejor[0]:
                                continue
                            if ma["cumple_contacto"] and ma["cumple_paso"] and ma["cumple_rg"] and ma["cumple_seccion"]:
                                mejor = (c, (hh, ff, DD2, mm, ii, gg))
    return mejor


def mejor_malla(proy, h, f):
    """Malla mas barata que cumple para una disposicion dada (barrido de D de mayor a menor)."""
    d = proy.d
    mejor = None
    for mm in range(3):
        for ii in range(len(CONDUCTORES)):
            for gg in range(4):
                for DD2 in range(int(2 * d["D_max"]), int(2 * d["D_min"]) - 1, -2):
                    c, _, ma, pe = proy.evaluar(h, f, DD2 / 2, mm, ii, gg)
                    if c is None:
                        return None
                    if ma["cumple_contacto"] and ma["cumple_paso"] and ma["cumple_rg"] and ma["cumple_seccion"]:
                        if mejor is None or c < mejor[0]:
                            mejor = (c, DD2, mm, ii, gg, ma["costo"], pe["costo"])
                        break   # D decrece: el primer D que cumple es el mas barato de esa combinacion
    return mejor


def barrido_alturas(proy, x_opt):
    """Para cada altura de mastil: costo minimo (filas entre pasillos y malla optimizadas por barrido).
    Sirve para mostrar por que el optimo del GA es el que es."""
    d = proy.d
    salida = []
    for h in range(d["altura_min"], d["altura_max"] + 1):
        mejor = None
        for f in range(d["filas_min"], d["filas_max"] + 1):
            if not proy.disposicion(h, f).factible:
                continue
            m = mejor_malla(proy, h, f)
            if m and (mejor is None or m[0] < mejor[0]):
                mejor = (m[0], f, len(proy.disposicion(h, f).mastiles), m[6], m[5])
        if mejor:
            salida.append(dict(h=h, filas=mejor[1], mastiles=mejor[2], costo_pecar=mejor[3],
                               costo_spt=mejor[4], costo_total=mejor[0]))
        else:
            salida.append(dict(h=h, filas=None, mastiles=None, costo_pecar=None, costo_spt=None, costo_total=None))
    return salida
