#!/usr/bin/env python3
"""
extract_names.py — heuristic person-name mentions from the srbas booking texts.

The edition has no persName markup, so names are found lexically: a known
early-modern given name (GIVEN_RE, case-insensitive because the transcription
writes "hans" and "Hans" alike), optionally a second given name, then a
capitalised surname token, optionally followed by an origin ("von Oberwilen").
Latin feast-day genitives (Johannis Baptistae, Martini), saints, inn names
(Zum Schlüssel) and the place tokens of the account taxonomy are excluded.

Inflection is normalised so the linker can compare with HGB name forms:
  given    dative  -en/-n  (Jacoben, Hansen, Wolffgangen, Petern) -> stem
  surname  genitive -s      (Felbers, Steigers, Nesers)            -> stem

    python3 extract_names.py        # -> srbas_name_mentions.csv (tracked)

Columns: year, pid, entry_id, account, raw, given_raw, given_norm,
         surname_raw, surname_norm, origin, uri
"""
import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
TEI = "{http://www.tei-c.org/ns/1.0}"

GIVEN_NAMES = """
hans hanns hansz hannsz hansen hannsen johann johanns johannes johans jacob jacoben
jakob peter petern martin martinen heinrich heinrichen heini fridlin fridlinen
friedlin marx marxen rudolff rudolffen rudolf andres andresen lienhart lienharten
lienhard leonhart steffan steffanen stephan ludwig ludwigen bernhart bernharten
bernhard daniel danielen georg georgen jörg jörgen jerg jergen caspar casparn
caspern sebastian sebastianen batt batten thuring thüring werlin wolff wolffen
wolffgang wolffgangen wolfgang conrat conraten conrad cunrat niclaus niclausen
claus clausz clausen clausn ulrich ulrichen uolrich ulin michel micheln thoman
thomas mathis mathisen matheus mattheus matthis lux luxen lucas simon simonen
bastian balthasar balthassar melchior jeronimus hieronymus onophrio onofrius
onoffrion crispin crispinus crispiano crispinen adelberg hug hugen lorentz lorentzen
lorenz laurentz frantz frantzen franz felix felixen urban urbanen adam abraham
isaac joseph emanuel samuel theodor basilius wilhelm wilhelmen wernher werner
hemman heman veltin veltinen valentin erhart erharten oswald oszwald oswalt
oswalten gilg gilgen egidius hansjacob hansrudolff hansheinrich hansulrich
hansjörg hansjerg hansconrat hanscunrat hansbernhart blesi blasi blasius beat
dietrich diebold diebolt theobald burckhart burkhart burckharten remigius
zacharias zacharia cristoffel christoffel stoffel cristan christian ambrosius
augustin bonifacius jost jodocus dursen durs urs moritz moritzen mauritius
bartlome bartholome bartholomeus philipp philips philippen benedict benedicten
hector hectorn gabriel gabrieln ambrosi anthoni anthonien anthonius anton
ursula margret margreth margareth elsbeth elsbet elisabeth barbara barbel agnes
catharina katharina catherin verena dorothea maria apollonia salome magdalena
madlen clara ottilia esther judith sara susanna justina rosina anastasia anna
"""
GIVEN_SET = set(GIVEN_NAMES.split())
GIVEN_ALT = "|".join(sorted(GIVEN_SET, key=len, reverse=True))

# tokens that look like a surname but are not
STOP_SURNAME = set("""
sant sankt st zum zun zur zu zem zen den der dem des die das und unnd uff auf
baptistae baptiste martini johannis jacobi georgii galli laurentii michaelis
andreae andree nicolai thomae matthiae mathie petri pauli mariae marie
septembris octobris novembris decembris januarii februarii martii aprilis maii
junii julii augusti jenners hornung mertzen aprellen meyen brachmonat höwmonat
augsten herbstmonat wynmonat wintermonat christmonat
nihil item suma summa gott christi domini anno
basel basell basell. grossbasel groszbasel kleinbasel mindernbasel
""".split())

# inn / house names that follow "zum/zur/zun": not persons
HOUSE_RE = re.compile(r"\b(?:zum|zur|zun|zu(?:m|r)?)\s+[A-ZÄÖÜ]", re.I)

CAP = r"[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜa-zäöüß]+)?"
# "Peter Im Hoff", "Hans Von Brunn", "Niclaus Zum Rappen": particle + token
PARTICLE_SN = r"(?:Im|Von|Vom|Zum|Zur|Zun|Zu|An|In|Uff|Ab|Am)\s+" + CAP
# given names match case-insensitively ("hans"/"Hans"), the surname must be
# capitalised — otherwise "Wolffen empfangen" yields the surname "empfangen"
NAME_RE = re.compile(
    r"(?<![\wäöüß])(?P<g1>(?i:" + GIVEN_ALT + r"))"
    r"(?:\s+(?P<g2>(?i:" + GIVEN_ALT + r")))?"
    r"\s+(?P<sn>" + PARTICLE_SN + r"|" + CAP + r")"
    r"(?:\s+(?P<origin>von|vonn|vom|ab|usz)\s+(?P<place>" + CAP + r"))?"
    r"(?![\wäöüß])",
)
# left context that puts the following name in the dative ("empfangen von
# Jacoben Gebharten"): the surname's -en is then an ending, not part of the name
DATIVE_LEFT = {"von", "vonn", "vom", "dem", "den", "herrn", "hern", "meister",
               "meyster", "doctor", "junker", "juncker", "mit", "by", "bi", "sampt",
               "zalt", "geben", "gaben", "gab"}


def load_account_places():
    """Place tokens from the account taxonomy (Amt Liestal, Muttenz, …)."""
    path = os.path.join(HERE, "tei", "o_srbas.konten.xml")
    places = set()
    if not os.path.exists(path):
        return places
    root = ET.parse(path).getroot()
    for name in root.iter(TEI + "name"):
        label = " ".join(name.itertext())
        for tok in re.split(r"[\s,]+", label):
            tok = tok.strip(".-")
            if tok and tok[0].isupper() and tok.lower() not in {"amt", "vogtei", "wittum", "hardvogt"}:
                places.add(tok.lower())
    return places


def norm_given(tok):
    t = tok.lower()
    if t in GIVEN_SET and t.endswith("en") and t[:-2] in GIVEN_SET:
        return t[:-2]                    # Jacoben -> jacob, Hansen -> hans
    if t.endswith("n") and t[:-1] in GIVEN_SET:
        return t[:-1]                    # Petern -> peter, Casparn -> caspar
    return t


def norm_surname(tok, dative=False):
    t = " ".join(tok.lower().strip(".,;:").split())
    if len(t) > 5 and t.endswith("s") and t[-2] in "rnlm":
        return t[:-1]                    # Felbers -> felber, Nesers -> neser
    if dative and " " not in t and len(t) > 5 and t.endswith("en"):
        return t[:-2]                    # (von) Gebharten -> gebhart; "Zum Rappen" stays
    return t


def is_bad_surname(sn, places):
    s = sn.lower()
    if s in STOP_SURNAME or s in places:
        return True
    # Latin genitives of feast days / saints
    if re.search(r"(ae|ii|is|orum)$", s) and len(s) > 5:
        return True
    return False


def find_names(text, places):
    for m in NAME_RE.finditer(text):
        sn = m.group("sn")
        if is_bad_surname(sn.split()[-1], places):
            continue
        # "Sant Peter Steinen" / "Zum Hans …" are not persons
        pre = text[max(0, m.start() - 6):m.start()].lower()
        if re.search(r"\b(sant|st\.)\s*$", pre):
            continue
        g1, g2 = m.group("g1"), m.group("g2")
        given_raw = g1 + (" " + g2 if g2 else "")
        given_norm = norm_given(g1) + (" " + norm_given(g2) if g2 else "")
        left = text[:m.start()].split()
        dative = (norm_given(g1) != g1.lower()
                  or bool(left) and left[-1].lower().strip(",.;") in DATIVE_LEFT)
        # a surname that is itself a given name ("Hans Jacob" + nothing) is a
        # two-part given name without surname: skip, too ambiguous
        if sn.lower() in GIVEN_SET:
            continue
        origin = ""
        if m.group("place") and m.group("place").lower() not in GIVEN_SET:
            origin = m.group("place")
        yield {
            "raw": m.group(0).strip(),
            "given_raw": given_raw, "given_norm": given_norm,
            "surname_raw": sn, "surname_norm": norm_surname(sn, dative),
            "origin": origin,
        }


def main():
    src = os.path.join(HERE, "srbas_entries.jsonl")
    out = os.path.join(HERE, "srbas_name_mentions.csv")
    if not os.path.exists(src):
        sys.exit(f"{src} missing; run extract_entries.py first")
    places = load_account_places()
    cols = ["year", "pid", "entry_id", "account", "raw", "given_raw",
            "given_norm", "surname_raw", "surname_norm", "origin", "uri"]
    n = entries = 0
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for line in open(src, encoding="utf-8"):
            r = json.loads(line)
            if r["kind"] != "bk_entry":
                continue
            hit = False
            for nm in find_names(r["text"], places):
                hit = True
                w.writerow({"year": r["year"], "pid": r["pid"],
                            "entry_id": r["entry_id"], "account": r["account"],
                            "uri": r["uri"], **nm})
                n += 1
            entries += hit
    print(f"{n} name mentions in {entries} bookings -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
