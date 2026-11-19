"""Stil der Adressbuch-Seiten in alle Seiten von eos_persons einsetzen (wiederholbar).

    python3 apply_adressbuch_style.py

Je Seite: assets/adressbuch.css (mit den lokalen Schriften Source Sans 3, Source Code Pro) am Ende von <head>,
und in der Kopfleiste ein Link zu Vernetzte Schweiz. Schon eingesetzte Teile werden nicht verdoppelt.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Schriften liegen lokal in assets/fonts (@font-face in adressbuch.css); keine Google Fonts.
HEAD = '<link rel="stylesheet" href="assets/adressbuch.css">\n'
VS = '<a class="page-tab vs-link" href="https://thodel.github.io/vernetzte-schweiz/">Vernetzte Schweiz ↗</a>'

for p in sorted(HERE.glob("*.html")):
    s = p.read_text(encoding="utf-8")
    if "assets/adressbuch.css" not in s and "</head>" in s:
        s = s.replace("</head>", HEAD + "</head>", 1)
    if "vs-link" not in s and '<nav id="page-nav">' in s:
        i = s.index('<nav id="page-nav">')
        j = s.index("</nav>", i)
        s = s[:j] + "  " + VS + "\n  " + s[j:]
    p.write_text(s, encoding="utf-8")
    print(p.name)
