"""
centre_periphery.py
===================
Centre/periphery spatial analysis of in_kind_share and value_schilling.

- Unit: unique geolocated dossier (one point per property).
- Centre = spatial median (densest core = Basel old town).
- Distance computed in LV95 metres (coords already projected → direct).
- Outputs: figures/centre_periphery_maps.png, figures/centre_periphery_gradient.png,
           centre_periphery.csv (dossierid, lat, lon, dist_m, value, in_kind_share)
           for the interactive Leaflet map.
"""
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

df = pd.read_parquet("features_doc.parquet")

# aggregate to dossier level (a property may appear in many documents)
g = (df[df.has_coord & df.coord_x.notna()]
     .groupby("dossierid")
     .agg(coord_x=("coord_x", "median"), coord_y=("coord_y", "median"),
          value_schilling=("value_schilling", "median"),
          in_kind_share=("in_kind_share", "mean"),
          n_docs=("doc_id", "count"))
     .reset_index())
print("unique geolocated dossiers:", len(g))

# centre = spatial median (robust to outliers)
cx, cy = g.coord_x.median(), g.coord_y.median()
g["dist_m"] = np.hypot(g.coord_x - cx, g.coord_y - cy)
print(f"centre (LV95): {cx:.1f}, {cy:.1f}   max dist {g.dist_m.max():.0f} m")

# ── join WGS84 lat/lon from dossiers_geo.json ────────────────────────────────
geo = json.load(open("dossiers_geo.json"))
ll = {f["id"]: (f["lat"], f["lon"]) for f in geo["features"]}
g["lat"] = g.dossierid.map(lambda d: ll.get(d, (None, None))[0])
g["lon"] = g.dossierid.map(lambda d: ll.get(d, (None, None))[1])

# ── correlation of distance with each variable (Spearman) ────────────────────
for var in ["in_kind_share", "value_schilling"]:
    sub = g[g[var].notna()]
    y = np.log1p(sub[var]) if var == "value_schilling" else sub[var]
    rho, p = stats.spearmanr(sub.dist_m, y)
    print(f"  distance vs {var:16s}: Spearman ρ={rho:+.3f}  p={p:.1e}  (n={len(sub)})")

# ── radial gradient: 150 m rings ─────────────────────────────────────────────
edges = np.arange(0, g.dist_m.max() + 150, 150)
g["ring"] = pd.cut(g.dist_m, edges)
grad = g.groupby("ring").agg(
    r_mid=("dist_m", "mean"),
    in_kind=("in_kind_share", "mean"),
    value=("value_schilling", "median"),
    n=("dossierid", "count")).dropna()
print("\nradial gradient (150 m rings):")
print(grad.round(3).to_string())

# ── figure 1: two maps ───────────────────────────────────────────────────────
fig, ax = plt.subplots(1, 2, figsize=(15, 7))
for a, (var, label, cmap, transform) in zip(ax, [
        ("value_schilling", "median value (log Schilling)", "viridis", True),
        ("in_kind_share", "in-kind obligation share", "magma", False)]):
    sub = g[g[var].notna()]
    c = np.log1p(sub[var]) if transform else sub[var]
    sc = a.scatter(sub.coord_x, sub.coord_y, c=c, s=14, cmap=cmap, alpha=.8,
                   edgecolors="none")
    a.scatter([cx], [cy], marker="+", s=300, c="red", linewidths=2, label="centre")
    for rr in [250, 500, 750, 1000]:
        a.add_patch(plt.Circle((cx, cy), rr, fill=False, ec="grey", lw=.6, alpha=.5))
    a.set_aspect("equal"); a.set_title(label)
    a.set_xlabel("LV95 E (m)"); a.set_ylabel("LV95 N (m)")
    plt.colorbar(sc, ax=a, fraction=0.046)
    a.legend(loc="upper right")
fig.suptitle("Basel HGB — spatial distribution of value & in-kind obligations "
             "(grey rings = 250 m)", y=1.02)
plt.tight_layout(); plt.savefig("figures/centre_periphery_maps.png", dpi=130,
                                bbox_inches="tight"); plt.close()

# ── figure 2: radial gradient ────────────────────────────────────────────────
fig, ax1 = plt.subplots(figsize=(9, 5.5))
ax1.plot(grad.r_mid, grad.in_kind, "o-", color="darkred", label="in-kind share")
ax1.set_xlabel("distance from centre (m)")
ax1.set_ylabel("mean in-kind obligation share", color="darkred")
ax1.tick_params(axis="y", labelcolor="darkred")
ax2 = ax1.twinx()
ax2.plot(grad.r_mid, grad.value, "s--", color="navy", label="median value")
ax2.set_ylabel("median value (Schilling)", color="navy")
ax2.tick_params(axis="y", labelcolor="navy")
ax2.set_yscale("log")
for x, n in zip(grad.r_mid, grad.n):
    ax1.annotate(f"n={n}", (x, grad.in_kind.loc[grad.r_mid == x].values[0]),
                 textcoords="offset points", xytext=(0, 8), fontsize=7, ha="center")
ax1.set_title("Centre→periphery gradient: in-kind obligations rise, value falls")
plt.tight_layout(); plt.savefig("figures/centre_periphery_gradient.png", dpi=130); plt.close()

# ── export for interactive map ───────────────────────────────────────────────
out = g[g.lat.notna()][["dossierid", "lat", "lon", "dist_m",
                        "value_schilling", "in_kind_share", "n_docs"]].copy()
out.to_csv("centre_periphery.csv", index=False)
print(f"\nwrote centre_periphery.csv ({len(out)} points), 2 figures")
