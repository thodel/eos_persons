"""
analyze_features.py
===================
Correlation & pattern analysis on the HGB document feature matrix
(features_doc.parquet, 75,447 docs). Statistical pattern discovery only —
no historical-trajectory assumptions.

Pipeline
  1. Build comparable numeric block: log1p heavy-tailed vars, z-score all.
  2. Source/era control: residualise on (source + time_bin) so correlations
     are net of "which archive / which era recorded it".
  3. Spearman correlation matrix (raw) + top correlated pairs.
  4. PCA → which variables co-move (loadings on PC1..PC5).
  5. KMeans clustering on PCA scores → emergent document types + profiles.
  6. Event-combination association mining: pairwise PMI/lift over event types,
     overall and within 25-year bins.
  7. Mixed-type: Cramér's V among categoricals; correlation ratio cat→numeric.
  8. Moran's I spatial autocorrelation on coordinates for key variables.

Outputs: figures/*.png  +  analysis_report.md
"""

import os, math, warnings
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
os.makedirs("figures", exist_ok=True)
RNG = 42
df = pd.read_parquet("features_doc.parquet")
N = len(df)
report = []
def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    report.append(line)

say(f"# HGB feature correlation & pattern analysis\n\nDocuments: **{N:,}**, raw columns: {df.shape[1]}\n")

# ── 1. Select & build comparable numeric block ───────────────────────────────
# Heavy-tailed → log1p; ratios/rates kept; identifiers/coords excluded here.
heavy = ["value_schilling", "value_per_participant", "price_per_property",
         "n_tokens", "pages", "distinct_entities", "n_events", "internal_date_span",
         "n_topological", "interest_capital_ratio"]
NUMERIC = [
    "year", "n_tokens", "pages", "n_events", "event_type_diversity",
    "distinct_entities", "mention_entity_ratio", "collective_actor_share",
    "named_persons_per_event_mean", "participants_per_event_mean", "role_diversity_mean",
    "n_witness", "attestation_rate", "buyer_seller_ratio", "payer_benef_ratio",
    "internal_date_span", "date_density", "interval_rate", "date_missing_rate",
    "status_marker_rate", "noble_rate", "master_rate", "academic_rate",
    "deceased_rate", "n_occ_distinct", "occ_entropy",
    "value_schilling", "value_per_participant", "interest_capital_ratio",
    "price_per_property", "in_kind_share", "currency_count",
    "conf_mean", "conf_std", "low_conf_share",
    # span rates (length-normalised)
    "sp_per_r", "sp_money_r", "sp_loc_r", "sp_fac_r", "sp_occ_r",
    "sp_owner_r", "sp_seizure_r", "sp_litigation_r", "sp_dead_r", "sp_title_r",
    # event multiplicities
    "ev_ownership_count", "ev_due-obligation_count", "ev_family_count",
    "ev_property-purchase_count", "ev_seizure_count", "ev_inheritance_count",
    "ev_litigation_count", "ev_employment_count",
]
NUMERIC = [c for c in NUMERIC if c in df.columns]
X = df[NUMERIC].copy()
for c in heavy:
    if c in X.columns:
        X[c] = np.log1p(X[c].clip(lower=0))
# median-impute, then z-score
X = X.apply(pd.to_numeric, errors="coerce")
X_imp = X.fillna(X.median())
Z = pd.DataFrame(StandardScaler().fit_transform(X_imp), columns=NUMERIC, index=df.index)

# ── 2. Source/era residualisation (control matrix) ───────────────────────────
# Regress each variable on dummy(source)+dummy(time_bin); keep residuals.
ctrl = pd.get_dummies(df[["source", "time_bin"]].astype("object").fillna("NA"),
                      columns=["source", "time_bin"], dtype=float)
ctrl = ctrl.values
# closed-form OLS hat: R = Z - C (C^+ Z)
C = np.hstack([np.ones((N, 1)), ctrl])
beta, *_ = np.linalg.lstsq(C, Z.values, rcond=None)
Zr = pd.DataFrame(Z.values - C @ beta, columns=NUMERIC, index=df.index)
say("## 1. Comparability transforms applied\n")
say(f"- {len(NUMERIC)} numeric features; {len(heavy)} log1p-transformed; all z-scored.")
say(f"- Residualised against **source ({df.source.nunique()} archives) + 25y time_bin** "
    f"to net out provenance/era confounds.\n")

# ── 3. Spearman correlation matrix + top pairs ───────────────────────────────
def top_pairs(corr, k=25):
    cc = corr.where(~np.tril(np.ones(corr.shape, bool)))
    s = cc.unstack().dropna()
    s = s.reindex(s.abs().sort_values(ascending=False).index)
    return s.head(k)

sp = Z.corr(method="spearman")
spr = Zr.corr(method="spearman")   # residualised
say("## 2. Strongest correlations (Spearman)\n")
say("### Raw (top 18)\n")
say("| variable A | variable B | ρ |\n|---|---|---|")
for (a, b), v in top_pairs(sp, 18).items():
    say(f"| {a} | {b} | {v:+.3f} |")
say("\n### After source+era control (top 18) — associations that survive confounds\n")
say("| variable A | variable B | ρ_resid |\n|---|---|---|")
for (a, b), v in top_pairs(spr, 18).items():
    say(f"| {a} | {b} | {v:+.3f} |")
say("")

# heatmap of a focused subset
focus = ["value_schilling", "value_per_participant", "named_persons_per_event_mean",
         "participants_per_event_mean", "role_diversity_mean", "event_type_diversity",
         "status_marker_rate", "noble_rate", "deceased_rate", "occ_entropy",
         "sp_seizure_r", "ev_litigation_count", "ev_inheritance_count",
         "in_kind_share", "mention_entity_ratio", "internal_date_span", "year"]
focus = [c for c in focus if c in spr.columns]
fig, ax = plt.subplots(figsize=(12, 10))
im = ax.imshow(spr.loc[focus, focus], cmap="RdBu_r", vmin=-.6, vmax=.6)
ax.set_xticks(range(len(focus))); ax.set_xticklabels(focus, rotation=90, fontsize=8)
ax.set_yticks(range(len(focus))); ax.set_yticklabels(focus, fontsize=8)
plt.colorbar(im, fraction=0.046).set_label("Spearman ρ (source+era controlled)")
ax.set_title("Residualised correlation matrix (focus variables)")
plt.tight_layout(); plt.savefig("figures/corr_heatmap.png", dpi=130); plt.close()
say("![correlation heatmap](figures/corr_heatmap.png)\n")

# ── 4. PCA ───────────────────────────────────────────────────────────────────
pca = PCA(n_components=8, random_state=RNG).fit(Z.values)
scores = pca.transform(Z.values)
ev = pca.explained_variance_ratio_
say("## 3. PCA — which variables co-move\n")
say("Explained variance: " + ", ".join(f"PC{i+1}={e*100:.1f}%" for i, e in enumerate(ev[:5]))
    + f"  (cumulative 5 = {ev[:5].sum()*100:.1f}%)\n")
load = pd.DataFrame(pca.components_[:5].T, index=NUMERIC,
                    columns=[f"PC{i+1}" for i in range(5)])
for pc in ["PC1", "PC2", "PC3"]:
    top = load[pc].reindex(load[pc].abs().sort_values(ascending=False).index).head(8)
    say(f"**{pc}** top loadings: " + ", ".join(f"{i} ({v:+.2f})" for i, v in top.items()))
say("")
fig, ax = plt.subplots(figsize=(8, 6))
sc = ax.scatter(scores[:, 0], scores[:, 1], s=3, alpha=.15,
                c=df["year"].fillna(df.year.median()), cmap="viridis")
plt.colorbar(sc).set_label("year")
ax.set_xlabel(f"PC1 ({ev[0]*100:.1f}%)"); ax.set_ylabel(f"PC2 ({ev[1]*100:.1f}%)")
ax.set_title("Documents in PC1–PC2 space (colour = year)")
plt.tight_layout(); plt.savefig("figures/pca_scatter.png", dpi=130); plt.close()
say("![pca scatter](figures/pca_scatter.png)\n")

# ── 5. KMeans clustering → emergent document types ───────────────────────────
K = 6
km = KMeans(n_clusters=K, random_state=RNG, n_init=10).fit(scores[:, :6])
df["cluster"] = km.labels_
say(f"## 4. Emergent document types (KMeans, k={K} on PCA scores)\n")
profile_cols = ["value_schilling", "named_persons_per_event_mean", "event_type_diversity",
                "status_marker_rate", "deceased_rate", "sp_seizure_r",
                "ev_inheritance_count", "ev_litigation_count", "in_kind_share", "year"]
profile_cols = [c for c in profile_cols if c in df.columns]
prof = df.groupby("cluster")[profile_cols].median()
prof["n_docs"] = df.cluster.value_counts().sort_index()
# dominant event combo & source per cluster
prof["top_event_combo"] = df.groupby("cluster")["event_combo"].agg(
    lambda s: s.replace("", np.nan).dropna().value_counts().index[0]
    if s.replace("", np.nan).dropna().size else "—")
prof["top_source"] = df.groupby("cluster")["source"].agg(
    lambda s: s.dropna().value_counts().index[0] if s.dropna().size else "—")
say(prof.round(2).to_markdown())
say("")

# ── 6. Event-combination association mining (PMI / lift) ──────────────────────
say("## 5. Event-type co-occurrence (PMI & lift)\n")
ev_classes = [c[3:-6] for c in df.columns if c.startswith("ev_") and c.endswith("_count")]
inc = pd.DataFrame({e: (df[f"ev_{e}_count"] > 0).astype(int) for e in ev_classes})
p = inc.mean()
pairs = []
for i, a in enumerate(ev_classes):
    for b in ev_classes[i+1:]:
        pab = (inc[a] & inc[b]).mean()
        if pab > 0 and p[a] > 0 and p[b] > 0:
            lift = pab / (p[a] * p[b])
            pmi = math.log(lift, 2)
            pairs.append((a, b, pab, lift, pmi, int((inc[a] & inc[b]).sum())))
pf = pd.DataFrame(pairs, columns=["event_a", "event_b", "p_joint", "lift", "pmi", "n_docs"])
pf = pf[pf.n_docs >= 50]
say("### Most positively associated event pairs (top lift)\n")
say(pf.sort_values("lift", ascending=False).head(12).round(3).to_markdown(index=False))
say("\n### Most *under*-associated (lowest lift, avoided combinations)\n")
say(pf.sort_values("lift").head(8).round(3).to_markdown(index=False))
say("")

# stability of a few strong pairs across 25y bins
watch = pf.sort_values("lift", ascending=False).head(4)[["event_a", "event_b"]].values.tolist()
say("### Lift of top pairs across 25-year bins (pattern stability)\n")
bins = sorted(df.time_bin.dropna().unique())
hdr = "| pair | " + " | ".join(str(int(b)) for b in bins) + " |"
say(hdr); say("|" + "---|" * (len(bins) + 1))
for a, b in watch:
    cells = []
    for bn in bins:
        sub = df[df.time_bin == bn]
        ia = (sub[f"ev_{a}_count"] > 0).astype(int); ib = (sub[f"ev_{b}_count"] > 0).astype(int)
        pa, pb = ia.mean(), ib.mean(); pj = (ia & ib).mean()
        cells.append(f"{(pj/(pa*pb)):.2f}" if pa > 0 and pb > 0 and pj > 0 else "·")
    say(f"| {a}×{b} | " + " | ".join(cells) + " |")
say("")

# ── 7. Mixed-type associations ───────────────────────────────────────────────
def cramers_v(a, b):
    ct = pd.crosstab(a, b)
    chi2 = stats.chi2_contingency(ct)[0]
    n = ct.values.sum(); r, k = ct.shape
    phi2 = chi2 / n
    phi2c = max(0, phi2 - (k-1)*(r-1)/(n-1))
    rc = r - (r-1)**2/(n-1); kc = k - (k-1)**2/(n-1)
    return math.sqrt(phi2c / max(min(kc-1, rc-1), 1e-9))

def corr_ratio(cat, num):
    m = num.notna() & cat.notna()
    cat, num = cat[m], num[m]
    if len(num) < 10: return np.nan
    grand = num.mean(); ss_t = ((num-grand)**2).sum()
    ss_b = sum(len(g)*(g.mean()-grand)**2 for _, g in num.groupby(cat))
    return math.sqrt(ss_b/ss_t) if ss_t > 0 else np.nan

say("## 6. Categorical associations\n")
cats = ["source", "time_bin", "language", "dossiertype", "cluster", "gov_org_present"]
cats = [c for c in cats if c in df.columns and df[c].nunique() > 1]
say("### Cramér's V among categoricals\n")
cv = pd.DataFrame(index=cats, columns=cats, dtype=float)
for i in cats:
    for j in cats:
        cv.loc[i, j] = 1.0 if i == j else cramers_v(df[i].astype("object").fillna("NA"),
                                                     df[j].astype("object").fillna("NA"))
say(cv.astype(float).round(3).to_markdown())
say("\n### Correlation ratio η (categorical → numeric); higher = category explains more variance\n")
num_for_eta = ["value_schilling", "named_persons_per_event_mean", "status_marker_rate",
               "in_kind_share", "event_type_diversity", "sp_seizure_r"]
num_for_eta = [c for c in num_for_eta if c in df.columns]
eta = pd.DataFrame(index=["source", "time_bin", "cluster"], columns=num_for_eta, dtype=float)
for cc in eta.index:
    for nn in num_for_eta:
        v = df[nn].copy()
        if nn in heavy: v = np.log1p(v.clip(lower=0))
        eta.loc[cc, nn] = corr_ratio(df[cc].astype("object"), v)
say(eta.astype(float).round(3).to_markdown())
say("")

# ── 8. Moran's I spatial autocorrelation ─────────────────────────────────────
say("## 7. Spatial autocorrelation (Moran's I, k-nearest=8)\n")
geo = df[df.has_coord & df.coord_x.notna()].copy()
geo = geo.drop_duplicates("dossierid")          # one point per property
say(f"Geo-located unique dossiers: {len(geo):,}")
from sklearn.neighbors import NearestNeighbors
coords = geo[["coord_x", "coord_y"]].values
k = 8
nn = NearestNeighbors(n_neighbors=k+1).fit(coords)
_, idx = nn.kneighbors(coords)
idx = idx[:, 1:]                                  # drop self
def morans_i(vals):
    v = np.asarray(vals, float)
    mask = ~np.isnan(v)
    z = v - np.nanmean(v)
    z[~mask] = 0
    n = mask.sum()
    num = 0.0; W = 0.0
    for a in range(len(v)):
        if not mask[a]: continue
        for b in idx[a]:
            if mask[b]:
                num += z[a]*z[b]; W += 1
    denom = np.nansum(z[mask]**2)
    return (n/W) * (num/denom) if denom > 0 and W > 0 else np.nan
say("\n| variable | Moran's I |\n|---|---|")
for v in ["value_schilling", "status_marker_rate", "noble_rate", "sp_seizure_r",
          "named_persons_per_event_mean", "in_kind_share", "ev_litigation_count"]:
    if v in geo.columns:
        vv = np.log1p(geo[v].clip(lower=0)) if v in heavy else geo[v]
        say(f"| {v} | {morans_i(vv.values):+.3f} |")
say("\n(I≈0 random; I>0 spatially clustered; I<0 dispersed)\n")

with open("analysis_report.md", "w") as f:
    f.write("\n".join(report))
say("\n---\nWrote analysis_report.md + figures/")
