"""
extract_features.py
===================
Streams the HGB source XML (hgb_full_26_05_29_05.xml, ~800 MB, 75k documents)
and emits a tidy **document-level feature matrix** as parquet (+ csv preview).

One row per <document>. Columns are grouped into families that are designed to
be *comparable across archives, currencies, and eras*:

  metadata      : year, time_bin (25y), source, language, pages, coords
  span_*        : per-class span counts (sp_<cls>_n) and length-normalised
                  rates per 100 tokens (sp_<cls>_r)
  participants  : witnesses, named persons per event type, participant counts,
                  role diversity, collective-actor share, mention/entity ratio
  temporal      : internal date span, date density, interval/date-missing rates
  events        : per-class event multiplicity (ev_<cls>_count) + persons-per-
                  event (ev_<cls>_persons_mean); event-combination set string
  status        : status-marker / noble / master / deceased rates, occ diversity
  economic      : unified value_schilling, value/participant, interest:capital,
                  price:property, in-kind share, currency count
  confidence    : mean/std span confidence, low-confidence share

All counts are ALSO exposed as rates so document length does not dominate any
correlation. Ratios (interest/capital, buyer/seller, value/participant) are
scale-free by construction.

Currency conversion uses an explicit, EDITABLE table (see RATES). The Gulden /
Taler rates are historical approximations for ca. 1400-1700 Basel and should be
reviewed against the project's numismatic reference before publication.
"""

import math
import re
from collections import defaultdict, Counter

from lxml import etree
import pandas as pd

# ── Config ──────────────────────────────────────────────────────────────────
XML_PATH   = "hgb_full_26_05_29_05.xml"
OUT_PARQUET = "features_doc.parquet"
OUT_PREVIEW = "features_doc_preview.csv"
BIN_WIDTH  = 25          # year time-bin width (requested)
BIN_ORIGIN = 1400
LOW_CONF   = 0.5         # threshold for "low confidence share"

# Currency unification → base unit = Schilling. EDITABLE / APPROXIMATE.
#   1 Pfund = 20 Schilling ; 1 Schilling = 12 Pfennig(=Denare=Heller~)
#   Gulden / Taler are gold-coin approximations and varied over time.
RATES = {
    "Schilling": 1.0,
    "Pfund":     20.0,
    "lb":        20.0,
    "Pfennig":   1.0 / 12.0,
    "Denare":    1.0 / 12.0,
    "Denar":     1.0 / 12.0,
    "Heller":    1.0 / 24.0,
    "Batzen":    1.5,
    "Gulden":    30.0,    # ~1.5 Pfund (approx, editable)
    "Taler":     36.0,    # ~1.2 Gulden (approx, editable)
    "Rappen":    1.0 / 10.0,
}
# Units that are goods/obligations in kind, NOT money — tracked separately.
IN_KIND = {"Huhn", "Hühner", "Ringe", "Höwer", "Kapaun", "Ei", "Eier",
           "Korn", "Wein", "Saum", "Viernzel", "Sester"}

# Person-bearing span class used to count "named persons".
PERSON_CLASSES = {"per"}

# Event classes we expose as dedicated columns (persons-per-event etc.).
MAIN_EVENTS = [
    "ownership", "due-obligation", "family", "due-payment", "property-purchase",
    "employment", "seizure", "inheritance", "civic-affiliation", "rent-purchase",
    "membership", "litigation", "redemption", "topological", "bequest",
    "testament", "pledge", "transfer", "debt",
]

# Non-principal participant roles bundled as "attestation" participants.
ATTEST_ROLES = {"witness", "consenting", "proclaimer", "addressee", "consent"}

NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*([A-Za-zÄÖÜäöüß.]+)")


def parse_money(norm):
    """Sum a (possibly compound) norm string into Schilling + in-kind count.

    Returns (schilling_value_or_None, in_kind_count, set_of_units_seen).
    """
    if not norm:
        return None, 0, set()
    total = 0.0
    got_money = False
    in_kind = 0
    units = set()
    for num, unit in NUM_RE.findall(norm):
        unit = unit.strip(".")
        units.add(unit)
        if unit in RATES:
            total += float(num) * RATES[unit]
            got_money = True
        elif unit in IN_KIND:
            in_kind += 1
    return (total if got_money else None), in_kind, units


POINT_RE = re.compile(r"POINT\(([-\d.]+)\s+([-\d.]+)\)")


def parse_point(loc):
    if not loc:
        return None, None
    m = POINT_RE.search(loc)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def entropy(counter):
    n = sum(counter.values())
    if n == 0:
        return 0.0
    h = 0.0
    for c in counter.values():
        p = c / n
        h -= p * math.log(p, 2)
    return h


# ── Union-find for coref → distinct entities ──────────────────────────────────
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def process_document(doc):
    """Return a flat dict of features for one <document> element."""
    row = {}
    meta = doc.find("metadata")
    if meta is None:
        return None

    year = meta.get("year")
    year = int(year) if year and year.isdigit() else None
    row["doc_id"]      = doc.get("id")
    row["dossierid"]   = meta.get("dossierid")
    row["dossiertype"] = meta.get("dossiertype") or None
    row["year"]        = year
    row["time_bin"]    = (BIN_ORIGIN + BIN_WIDTH * ((year - BIN_ORIGIN) // BIN_WIDTH)
                          if year is not None else None)
    row["source"]      = meta.get("source") or None
    row["language"]    = meta.get("language") or None
    row["pages"]       = int(meta.get("pages")) if (meta.get("pages") or "").isdigit() else None
    row["checked_by_gpt"] = meta.get("checked_by_gpt") == "true"
    cx, cy = parse_point(meta.get("location"))
    row["coord_x"], row["coord_y"] = cx, cy
    row["has_coord"] = cx is not None

    # ── tokens ───────────────────────────────────────────────────────────────
    text_el = doc.find("text")
    n_tokens = len(text_el.findall("token")) if text_el is not None else 0
    row["n_tokens"] = n_tokens
    tok = max(n_tokens, 1)

    # ── spans ────────────────────────────────────────────────────────────────
    span_class = {}          # span id -> class
    span_conf  = []
    span_norm_val = {}       # span id -> schilling value (money)
    class_counts = Counter()
    title_texts = []
    occ_texts = []
    grp_persons = 0
    money_in_kind = 0
    currency_units = set()
    n_money_money = 0        # money spans with a monetary value

    spans_el = doc.find("spans")
    if spans_el is not None:
        for sp in spans_el.iter("span"):
            sid = sp.get("id")
            cls = sp.get("class")
            if sid is not None:
                span_class[sid] = cls
            if cls:
                class_counts[cls] += 1
            conf = sp.get("confidence")
            if conf:
                try:
                    span_conf.append(float(conf))
                except ValueError:
                    pass
            if cls in PERSON_CLASSES and sp.get("numerus") == "grp":
                grp_persons += 1
            if cls == "money":
                val, ik, units = parse_money(sp.get("norm"))
                if sid is not None and val is not None:
                    span_norm_val[sid] = val
                if val is not None:
                    n_money_money += 1
                money_in_kind += ik
                currency_units |= (units & set(RATES))
            elif cls == "title":
                title_texts.append((sp.get("text") or "").strip().lower())
            elif cls == "occ":
                t = (sp.get("text") or "").strip().lower()
                # strip leading articles for diversity counting
                t = re.sub(r"^(der|die|das|des|dem|den)\s+", "", t)
                if t:
                    occ_texts.append(t)

    n_per = class_counts.get("per", 0)
    per_den = max(n_per, 1)

    # span counts + rates per 100 tokens
    for cls, c in class_counts.items():
        row[f"sp_{cls}_n"] = c
        row[f"sp_{cls}_r"] = 100.0 * c / tok

    # ── coref → distinct entities ──────────────────────────────────────────────
    uf = UF()
    person_ids = {sid for sid, c in span_class.items() if c in PERSON_CLASSES}
    rel_el = doc.find("relations")
    if rel_el is not None:
        for rel in rel_el.iter("relation"):
            if rel.get("class") == "coref":
                a, b = rel.get("from"), rel.get("to")
                if a is not None and b is not None:
                    uf.union(a, b)
    roots = {uf.find(p) for p in person_ids}
    distinct_entities = len(roots) if person_ids else 0
    row["distinct_entities"] = distinct_entities
    row["mention_entity_ratio"] = (n_per / distinct_entities) if distinct_entities else None
    row["collective_actor_share"] = (grp_persons / per_den)

    # ── events ─────────────────────────────────────────────────────────────────
    role_counts = Counter()
    ev_count = Counter()
    ev_persons = defaultdict(list)        # event class -> persons-per-event list
    ev_participants = []                   # participant slots per event
    ev_role_div = []                       # role-label entropy per event
    interest_total = capital_total = price_total = 0.0
    n_property_roles = 0
    all_dates = []                         # numeric years seen in date spans
    event_set = set()

    eg_el = doc.find("eventGroups")
    if eg_el is not None:
        for eg in eg_el.findall("eventGroup"):
            ecls = eg.get("class")
            if not ecls:
                continue
            ev_count[ecls] += 1
            event_set.add(ecls)
            ev_role_labels = Counter()
            person_refs = set()
            participant_slots = 0
            for ev in eg.iter("event"):
                for r in ev.findall("role"):
                    rlabel = r.get("role")
                    ref = r.get("ref")
                    if not rlabel:
                        continue
                    role_counts[rlabel] += 1
                    ev_role_labels[rlabel] += 1
                    refcls = span_class.get(ref)
                    if refcls in PERSON_CLASSES:
                        person_refs.add(uf.find(ref))   # distinct entity
                        participant_slots += 1
                    if rlabel == "property":
                        n_property_roles += 1
                    if rlabel == "interest" and ref in span_norm_val:
                        interest_total += span_norm_val[ref]
                    elif rlabel == "capital" and ref in span_norm_val:
                        capital_total += span_norm_val[ref]
                    elif rlabel == "price" and ref in span_norm_val:
                        price_total += span_norm_val[ref]
            ev_persons[ecls].append(len(person_refs))
            ev_participants.append(participant_slots)
            ev_role_div.append(entropy(ev_role_labels))

    # event multiplicity + persons-per-event for main classes
    n_events = sum(ev_count.values())
    row["n_events"] = n_events
    row["event_type_diversity"] = len([c for c in ev_count if ev_count[c]])
    row["event_combo"] = "|".join(sorted(event_set))     # for co-occurrence mining
    for ecls in MAIN_EVENTS:
        row[f"ev_{ecls}_count"] = ev_count.get(ecls, 0)
        pl = ev_persons.get(ecls)
        row[f"ev_{ecls}_persons_mean"] = (sum(pl) / len(pl)) if pl else None
    row["participants_per_event_mean"] = (sum(ev_participants) / len(ev_participants)
                                          if ev_participants else None)
    row["role_diversity_mean"] = (sum(ev_role_div) / len(ev_role_div)
                                  if ev_role_div else None)
    row["named_persons_per_event_mean"] = (
        sum(sum(v) for v in ev_persons.values()) / n_events if n_events else None)

    # ── participant-structure (document level) ──────────────────────────────────
    row["n_witness"]      = role_counts.get("witness", 0)
    row["n_attestation"]  = sum(role_counts.get(r, 0) for r in ATTEST_ROLES)
    row["attestation_rate"] = sum(role_counts.get(r, 0) for r in ATTEST_ROLES) / per_den
    n_buyer  = role_counts.get("buyer", 0)
    n_seller = role_counts.get("seller", 0)
    n_payer  = role_counts.get("payer", 0)
    n_benef  = role_counts.get("beneficiary", 0)
    row["buyer_seller_ratio"]   = (n_buyer / n_seller) if n_seller else None
    row["payer_benef_ratio"]    = (n_payer / n_benef) if n_benef else None

    # ── temporal (within-document, no trajectory assumption) ────────────────────
    if spans_el is not None:
        for sp in spans_el.iter("span"):
            if sp.get("class") == "date":
                for m in re.findall(r"\b(1[3-7]\d{2})\b", sp.get("text") or ""):
                    all_dates.append(int(m))
    n_date = class_counts.get("date", 0)
    if all_dates:
        span_years = max(all_dates) - min(all_dates)
        row["internal_date_span"] = span_years
        row["date_density"] = n_date / (span_years + 1)
    else:
        row["internal_date_span"] = None
        row["date_density"] = None
    row["n_dates_parsed"] = len(all_dates)
    row["interval_rate"]      = role_counts.get("interval", 0) / max(n_events, 1)
    row["date_missing_rate"]  = role_counts.get("date-missing", 0) / max(n_events, 1)

    # ── status / qualifiers ─────────────────────────────────────────────────────
    noble_kw  = ("jkr", "jr", "junck", "junk", "ritter", "edel", "freiherr")
    master_kw = ("meister", "mr", "m .")
    acad_kw   = ("dr", "doctor", "d .", "licentiat")
    n_noble = sum(any(k in t for k in noble_kw) for t in title_texts)
    n_master = sum(any(k in t for k in master_kw) for t in title_texts)
    n_acad = sum(any(k in t for k in acad_kw) for t in title_texts)
    row["status_marker_rate"] = len(title_texts) / per_den
    row["noble_rate"]   = n_noble / per_den
    row["master_rate"]  = n_master / per_den
    row["academic_rate"] = n_acad / per_den
    row["deceased_rate"] = (class_counts.get("dead", 0) + role_counts.get("decedent", 0)) / per_den
    occ_counter = Counter(occ_texts)
    row["n_occ_distinct"] = len(occ_counter)
    row["occ_entropy"]    = entropy(occ_counter)
    row["gov_org_present"] = (class_counts.get("gov", 0) + class_counts.get("org", 0)) > 0
    row["n_topological"]  = class_counts.get("topological", 0)

    # ── economic ────────────────────────────────────────────────────────────────
    total_value = sum(span_norm_val.values())
    row["value_schilling"]    = total_value if span_norm_val else None
    row["n_money_spans"]      = n_money_money
    row["value_per_participant"] = (total_value / distinct_entities
                                    if (span_norm_val and distinct_entities) else None)
    row["interest_capital_ratio"] = (interest_total / capital_total) if capital_total else None
    row["price_per_property"] = (price_total / n_property_roles) if n_property_roles else None
    total_obl = n_money_money + money_in_kind
    row["in_kind_share"] = (money_in_kind / total_obl) if total_obl else None
    row["currency_count"] = len(currency_units)

    # ── confidence ──────────────────────────────────────────────────────────────
    if span_conf:
        m = sum(span_conf) / len(span_conf)
        row["conf_mean"] = m
        row["conf_std"]  = (sum((c - m) ** 2 for c in span_conf) / len(span_conf)) ** 0.5
        row["low_conf_share"] = sum(c < LOW_CONF for c in span_conf) / len(span_conf)
    else:
        row["conf_mean"] = row["conf_std"] = row["low_conf_share"] = None

    return row


def main():
    rows = []
    n = 0
    ctx = etree.iterparse(XML_PATH, events=("end",), tag="document")
    for _, doc in ctx:
        r = process_document(doc)
        if r is not None:
            rows.append(r)
        n += 1
        if n % 5000 == 0:
            print(f"  …{n} documents", flush=True)
        # free memory: clear element and preceding siblings
        doc.clear()
        while doc.getprevious() is not None:
            del doc.getparent()[0]
    print(f"parsed {n} documents", flush=True)

    df = pd.DataFrame(rows)
    # fill span count/rate NaNs (a class simply absent in a doc) with 0
    for col in df.columns:
        if col.startswith(("sp_", "ev_")) and col.endswith(("_n", "_r", "_count")):
            df[col] = df[col].fillna(0)
    df.to_parquet(OUT_PARQUET, index=False)
    df.head(200).to_csv(OUT_PREVIEW, index=False)
    print(f"wrote {OUT_PARQUET}  shape={df.shape}")
    print(f"wrote {OUT_PREVIEW} (200-row preview)")
    print("columns:", list(df.columns))


if __name__ == "__main__":
    main()
