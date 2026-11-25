"""Figuras de la app (matplotlib)."""
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Circle
from matplotlib.lines import Line2D
from shapely import affinity
from shapely.geometry import box

from motor import huella_sombra

C_TERRENO, C_MESA, C_CASETA = "#222222", "#3b6ea5", "#b22222"
C_MALLA, C_MASTIL, C_SOMBRA, C_PASILLO = "#2e8b57", "#e07b00", "#555555", "#f3e9c6"


def _base(ax, terreno, disp, pasillos=True):
    ax.plot(*terreno.exterior.xy, color=C_TERRENO, lw=2)
    if pasillos:
        x0, _, x1, _ = terreno.bounds
        for (ya, yb) in disp.pasillos:
            franja = box(x0, ya, x1, yb).intersection(terreno)
            for g in getattr(franja, "geoms", [franja]):
                if g.geom_type == "Polygon" and not g.is_empty:
                    ax.fill(*g.exterior.xy, color=C_PASILLO, zorder=0, lw=0)
    for m in disp.mesas:
        ax.fill(*m.exterior.xy, facecolor=C_MESA, edgecolor="none", zorder=2)
    ax.fill(*disp.caseta.exterior.xy, facecolor=C_CASETA, edgecolor="black", lw=0.8, zorder=3)
    ax.set_aspect("equal")
    ax.set_xlabel("Este (m)"); ax.set_ylabel("Norte (m)")
    ax.grid(alpha=0.2)


def plano_paneles(terreno, disp, sub_xy):
    fig, ax = plt.subplots(figsize=(8, 8.5))
    _base(ax, terreno, disp)
    ax.annotate("S/E Santa Fe 110 kV\n(%.0f m al NO)" % math.hypot(*sub_xy), xy=(5, terreno.bounds[3] - 5),
                xytext=(10, terreno.bounds[3] + 8), fontsize=8, arrowprops=dict(arrowstyle="->"))
    ax.legend(handles=[Patch(facecolor=C_MESA, label="Mesas FV (%d)" % len(disp.mesas)),
                       Patch(facecolor=C_PASILLO, label="Pasillos de %.1f m (mantenimiento y mastiles)" % disp.ancho_pasillo),
                       Patch(facecolor=C_CASETA, label="Caseta tecnica (inversores + BESS)")],
              loc="lower right", fontsize=8)
    ax.set_title("Terreno, caseta y paneles con pasillos")
    fig.tight_layout()
    return fig


def plano_pecar(terreno, disp, vec, pecar=None, mostrar_sombras=True):
    fig, ax = plt.subplots(figsize=(8, 8.5))
    _base(ax, terreno, disp)
    huella = huella_sombra(vec * disp.h)
    for (x, y) in disp.mastiles:
        ax.add_patch(Circle((x, y), disp.radio_paneles, color=C_MASTIL, alpha=0.07, lw=0))
        if mostrar_sombras:
            s = affinity.translate(huella, x, y)
            ax.fill(*s.exterior.xy, facecolor=C_SOMBRA, alpha=0.18, edgecolor="none", zorder=1)
    for (a, b, y) in disp.cables:
        ax.plot([a, b], [y, y], color="#7a3b00", lw=1.6, zorder=4)
    ax.plot(disp.mastiles[:, 0], disp.mastiles[:, 1], "^", color=C_MASTIL, ms=6, mec="black", mew=0.4, zorder=5)
    extra = [Line2D([0], [0], color="#7a3b00", lw=1.6,
                    label="Cables de guarda Cu 50 mm2 (%d, %.0f m)" % (len(disp.cables), sum(b - a for a, b, _ in disp.cables)))] if disp.cables else []
    ax.legend(handles=extra + [Line2D([0], [0], marker="^", ls="", color=C_MASTIL, mec="black",
                              label="Mastiles h = %d m (%d)" % (disp.h, len(disp.mastiles))),
                       Patch(facecolor=C_MASTIL, alpha=0.25,
                             label="Zona protegida a la altura de los paneles (r = %.1f m)" % disp.radio_paneles),
                       Patch(facecolor=C_SOMBRA, alpha=0.4, label="Sombra posible de cada mastil (9-15 h, todo el ano)")],
              loc="lower right", fontsize=8)
    ax.set_title("Mastiles y cables de guarda (esfera rodante), con la sombra como restriccion")
    fig.tight_layout()
    return fig


def plano_malla(terreno, disp, malla, pecar):
    fig, ax = plt.subplots(figsize=(8, 8.5))
    _base(ax, terreno, disp, pasillos=False)
    for s in malla["segmentos"]:
        ax.plot(*s.xy, color=C_MALLA, lw=0.7, alpha=0.8)
    ax.plot(*malla["anillo"].xy, color=C_MALLA, lw=1.6)
    if malla["varillas"]:
        v = np.array(malla["varillas"])
        ax.plot(v[:, 0], v[:, 1], "o", color=C_MALLA, ms=3.5)
    for (a, b) in pecar["uniones"]:
        ax.plot([a[0], b[0]], [a[1], b[1]], "--", color="#d2691e", lw=1)
    for (a, b, y) in disp.cables:
        ax.plot([a, b], [y, y], color="#7a3b00", lw=1.2, zorder=4)
    ax.plot(disp.mastiles[:, 0], disp.mastiles[:, 1], "^", color=C_MASTIL, ms=5, mec="black", mew=0.3, zorder=5)
    if pecar["varillas_pr"]:
        v = np.array(pecar["varillas_pr"])
        ax.plot(v[:, 0], v[:, 1], "o", mfc="none", mec="#8b4513", ms=7, mew=1.2)
    ax.legend(handles=[Line2D([0], [0], color=C_MALLA, label="Malla D = %.1f m, %s" % (malla["D"], malla["conductor"])),
                       Line2D([0], [0], marker="o", ls="", color=C_MALLA, label="Varillas de la malla (%d)" % malla["nR"]),
                       Line2D([0], [0], ls="--", color="#d2691e", label="Union mastil-malla (%.0f m)" % pecar["L_union"]),
                       Line2D([0], [0], marker="o", ls="", mfc="none", mec="#8b4513",
                              label="Varilla al pie del mastil (%d)" % len(pecar["varillas_pr"]))],
              loc="lower right", fontsize=8)
    ax.set_title("Malla de puesta a tierra (IEEE 80) unida al PECAR")
    fig.tight_layout()
    return fig


def curva_D(barrido, D_opt, Et, Ep):
    D = [b["D"] for b in barrido]
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    ax[0].plot(D, [b["Em"] for b in barrido], color="#3b6ea5", label="Tension de malla Em")
    ax[0].plot(D, [b["Es"] for b in barrido], color="#7a5195", label="Tension de paso Es")
    ax[0].axhline(Et, color="#3b6ea5", ls="--", lw=1, label="Contacto tolerable %.0f V" % Et)
    ax[0].axhline(Ep, color="#7a5195", ls="--", lw=1, label="Paso tolerable %.0f V" % Ep)
    ax[0].axvline(D_opt, color="black", lw=0.8)
    ax[0].set_xlabel("Espaciamiento D (m)"); ax[0].set_ylabel("V"); ax[0].legend(fontsize=7); ax[0].grid(alpha=0.2)
    ax[1].plot(D, [b["costo"] / 1e6 for b in barrido], color=C_MALLA)
    ax[1].axvline(D_opt, color="black", lw=0.8)
    ax[1].set_xlabel("Espaciamiento D (m)"); ax[1].set_ylabel("Costo de la malla (millones COP)"); ax[1].grid(alpha=0.2)
    fig.tight_layout()
    return fig


def curva_alturas(tabla, h_opt):
    t = [r for r in tabla if r["costo_total"]]
    h = [r["h"] for r in t]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.bar(h, [r["costo_spt"] / 1e6 for r in t], color=C_MALLA, label="SPT (malla)")
    ax.bar(h, [r["costo_pecar"] / 1e6 for r in t], bottom=[r["costo_spt"] / 1e6 for r in t], color=C_MASTIL,
           label="PECAR (mastiles, bajantes, uniones)")
    for r in t:
        ax.text(r["h"], r["costo_total"] / 1e6 + 8, "%d" % r["mastiles"], ha="center", fontsize=7)
    if h_opt in h:
        r = t[h.index(h_opt)]
        ax.annotate("optimo", (h_opt, r["costo_total"] / 1e6), xytext=(h_opt, r["costo_total"] / 1e6 + 60),
                    ha="center", arrowprops=dict(arrowstyle="->"))
    ax.set_xlabel("Altura del mastil (m)  [numero sobre la barra = mastiles]")
    ax.set_ylabel("Millones COP"); ax.legend(fontsize=8); ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    return fig
