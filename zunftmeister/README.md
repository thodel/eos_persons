# Zunftmeister der Basler Zünfte

`zunftmeister.csv` sammelt die veröffentlichten Meisterlisten von acht Basler Zünften (722 Einträge, 1255–2025).
`../link_zunftmeister.py` gleicht die Meister bis 1710 mit den zusammengeführten eos-Personen (`merged_persons.json`) und in einem zweiten Durchlauf mit allen HGB-Personen (`persons_resolved.json`) ab und schreibt `../link_zunftmeister_candidates.csv`.

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
python3 link_zunftmeister.py --hgb ''   # nur die zusammengeführten Personen
```

Die Ausgabe ist eine Kandidatenliste zur Durchsicht, keine automatische Verknüpfung. Die Spalte `pool` sagt, gegen welche Personenmenge verglichen wurde.

**`pool = merged`** – die 3 502 zusammengeführten Personen (`merged_persons.json`, mit HBLS-, HLS- oder GND-Bezug). Ein Meister wird verknüpft, wenn Nachname und Vorname übereinstimmen (Schreibvarianten wie Fäsch/Faesch erlaubt) und die Lebensdaten zum Wahljahr passen (mindestens 22 Jahre alt, nicht tot).

| Stufe | Bedeutung |
|---|---|
| `stark` | genauer Name, Lebensdaten passen, und die Person ist schon als Zunftmeister erfasst oder übt ein Gewerbe der Zunft aus |
| `wahrscheinlich` | genauer Name oder Schreibvariante mit gleichem Vornamen, Lebensdaten passen |
| `möglich` | nur Erwähnungsspanne passt, oder die Vornamen unterscheiden sich in der Zahl (z. B. «Hans Heinrich» / «Johannes») |

**`pool = hgb`** – alle 127 175 Personen des HGB-Index (`persons_resolved.json`), also auch ohne HBLS-, HLS- oder GND-Bezug. Diese Personen haben keine Lebensdaten, nur die Spanne ihrer Erwähnungen (`mention_span`); sie muss das Wahljahr einschliessen (±12–15 Jahre; Personen mit mehr als 75 Jahren Spanne sind verkettete Namensvettern und fallen weg; wer vor der Wahl starb, auch).

| Stufe | Bedeutung |
|---|---|
| `wahrscheinlich` | genauer Name, Erwähnung innerhalb von 5 Jahren um die Amtszeit, und ein Beleg: Titel «Zunftmeister», die Zunft in der Organisation (`guild_org`) oder ein Gewerbe der Zunft (`trade_match`) |
| `möglich` | Name passt und die Erwähnungen liegen in den richtigen Jahrzehnten; nur gelistet, wenn es höchstens 3 solche Kandidaten für den Meister gibt (`namesakes`) oder ein Zunftmeister-Titel / die Zunft vorliegt |

`person_id` ist bei bereits zusammengeführten Personen die Id aus `merged_persons.json`, sonst der HGB-Schlüssel `Name#erstes Jahr`; die Spalten `occupations` und `n_dossiers` helfen beim Prüfen. Maximal sechs Kandidaten je Meister und Pool. Das Gewerbe-Kriterium ist grosszügig («Kaufmann» zählt bei Safran und Weinleuten), `namesakes` zeigt, wie viele Namensvettern in Frage kommen: bei Socin, Burckhardt oder Fäsch lässt sich nur von Hand trennen.

Stand 20.11.2026, 476 Meister bis 1710:

| Pool | Meister mit Kandidaten | Zeilen | davon |
|---|---|---|---|
| merged | 32 | 33 | 9 stark, 22 wahrscheinlich, 2 möglich |
| hgb | 225 | 385 | 53 wahrscheinlich, 332 möglich |
| zusammen | 234 | | |

Tests: `tests/test_link_zunftmeister.py`.
