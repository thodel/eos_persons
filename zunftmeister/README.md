# Zunftmeister der Basler Zünfte

`zunftmeister.csv` sammelt die veröffentlichten Meisterlisten von acht Basler Zünften (722 Einträge, 1255–2025).
`../link_zunftmeister.py` gleicht die Meister bis 1710 mit den zusammengeführten eos-Personen (`merged_persons.json`) ab und schreibt `../link_zunftmeister_candidates.csv`.

| Zunft | Einträge | Zeitraum | Quelle (abgerufen 20.11.2026) |
|---|---|---|---|
| Weinleuten | 126 | 1311–2022 | <https://weinleuten.ch/weinleuten/meister/> |
| Hausgenossen | 89 | 1358–2019 | <https://hausgenossen.ch/verzeichnis/> |
| Gartnern | 117 | 1284–2022 | <https://gartnernzunft.ch/vorgesetzte/meisterliste> (nur Funktion «Meister») |
| Gerbern | 74 | 1358–2024 | <https://www.gerbernzunft.ch/historisch/meisterchronik/> |
| Safran | 98 | 1358–2019 | <https://www.safranzunft.ch/zunft/zunftmeister/> (Zusatzinfos gekürzt auf Beruf und Ämter) |
| Goldener Stern | 41 | 1383–2025 | <https://www.zunftzumgoldenenstern.ch/zunft/vorstand>, nach Steiner, *Zunft zum goldenen Stern* (1956) |
| Schmieden | 116 | 1255–2016 | «Die Zunftmeister von 1255 bis Heute», Text der Zunft (vom Auftraggeber bereitgestellt) |
| Schiffleuten | 61 | 1358–2025 | «Meisterliste» der Zunft (vom Auftraggeber bereitgestellt) |

Für Schuhmachern, Schneidern, Kürschnern und Spinnwettern finden sich öffentlich keine Meisterlisten (Schneidern: «Wappenbuch der Vorgesetzten seit 1691» nur für Mitglieder; Schuhmachern: Zunftrodel nur intern).
Zünfte, die gemeinsam einen Meister stellten (Schuhmachern/Gerbern, Schneidern/Kürschnern, Goldener Stern/Himmel), erscheinen nur mit der Hälfte; so enthält die Liste des Goldenen Sterns keine Meister zum Himmel.

## Spalten

`zunft`, `year_from` (Jahr der Wahl, wie veröffentlicht), `year_to` (Ende der Amtszeit, wenn die Quelle eines nennt; bei Weinleuten das letzte Jahr der «ebenso»-Reihe), `name` (wie in der Quelle, Wortfolge uneinheitlich), `note` (Beruf, Titel, Hinweise der Quelle), `source`.

Eigenheiten der Quellen:
- Die Wortfolge schwankt: meist «Vorname Nachname», bei Schmieden häufig «Nachname Vorname». Der Abgleich probiert beide.
- Weinleuten, Gartnern und Hausgenossen kennen gleichzeitig amtierende Meister («neuer»/«alter»); die Amtszeiten überlappen deshalb.
- Beim Goldenen Stern stehen die Jahre von 1529 bis 1764 im Wappenbuch ohne Jahreszahl; sie sind Näherungen (Notiz in `note`).
- Die Listen enthalten Schreibfehler der Quellen (z. B. Weinleuten «1972» für 1792, «1953» für 1853).

## Abgleich

```bash
python3 link_zunftmeister.py            # -> link_zunftmeister_candidates.csv
```

Ein Meister wird mit einer Person verknüpft, wenn Nachname und Vorname übereinstimmen (Schreibvarianten wie Fäsch/Faesch erlaubt) und die Lebensdaten – oder, ohne Lebensdaten, die Spanne der HGB-Erwähnungen – zum Wahljahr passen (mindestens 22 Jahre alt, nicht tot). Stufen:

| Stufe | Bedeutung |
|---|---|
| `stark` | genauer Name, Lebensdaten passen, und die Person ist schon als Zunftmeister erfasst oder übt ein Gewerbe der Zunft aus |
| `wahrscheinlich` | genauer Name oder Schreibvariante mit gleichem Vornamen, Lebensdaten passen |
| `möglich` | nur Erwähnungsspanne passt, oder die Vornamen unterscheiden sich in der Zahl (z. B. «Hans Heinrich» / «Johannes») |

Stand 20.11.2026: 476 Meister bis 1710, davon 28 mit Kandidaten (29 Zeilen: 8 stark, 19 wahrscheinlich, 2 möglich).
Die geringe Trefferquote hat einen einfachen Grund: `merged_persons.json` enthält nur Personen mit HBLS-, HLS- oder GND-Bezug, nicht alle HGB-Namen. Die Ausgabe ist eine Kandidatenliste zur Durchsicht, keine automatische Verknüpfung; Namensvettern mit gleichem Lebensfenster (Socin, Burckhardt, Fäsch) lassen sich nur von Hand trennen.

Tests: `tests/test_link_zunftmeister.py`.
