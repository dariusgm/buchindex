# buchindex

Indexiert einen lokalen Ordner mit PDF- und EPUB-Büchern in eine
[Meilisearch](https://www.meilisearch.com/)-Instanz. Jedes Buch wird in Passagen
zerlegt, die Kapitel, Seitenbereich und Dateipfad behalten.

## Setup

Voraussetzungen: [uv](https://docs.astral.sh/uv/) und die Systempakete unten.

```sh
uv sync
cp .env.example .env   # Werte eintragen
uv run buchindex check
```

### Python-Version

Das Projekt läuft mit **Python 3.14**. Python 3.15 wurde geprüft und verworfen:
`pymupdf` 2.x hängt von `onnxruntime` ab, und dafür gibt es (Stand 11.11.2026,
Version 1.31.1) keine Wheels für 3.15.

### Systempakete

Linux (apt):

```sh
sudo apt install tesseract-ocr tesseract-ocr-deu ghostscript qpdf pandoc
```

macOS (brew):

```sh
brew install tesseract tesseract-lang ghostscript qpdf pandoc
```

| Programm    | Zweck                         |
|-------------|-------------------------------|
| `tesseract` | OCR für Scans                 |
| `gs`, `qpdf`| von ocrmypdf benötigt         |
| `pandoc`    | EPUB-Konvertierung            |

Die CLI prüft beim Start, ob diese Programme im PATH liegen, und bricht sonst
mit einer Meldung ab, die das fehlende Paket nennt.

## Meilisearch lokal starten

```sh
docker run -d --name meili-local -p 7700:7700 \
  -e MEILI_MASTER_KEY=<langer-zufaelliger-key> \
  -e MEILI_ENV=development \
  -v meili_data:/meili_data \
  getmeili/meilisearch:latest
```

- Der Master-Key kommt aus der `.env` (`MEILI_KEY`), niemals in den Code.
  Einen Key erzeugt `openssl rand -hex 32`.
- Das Volume `meili_data` sorgt dafür, dass der Index Neustarts überlebt.
- `MEILI_ENV=development` ist nur für den lokalen Betrieb gedacht.

Danach prüft `uv run buchindex check`, ob Meilisearch erreichbar und der Key
gültig ist.

## Konfiguration

Die gesamte Konfiguration erfolgt über Umgebungsvariablen. Optional liest die
CLI eine `.env`-Datei aus dem aktuellen Verzeichnis (oder einem übergeordneten).
Bereits gesetzte Umgebungsvariablen haben Vorrang vor der `.env`.

| Variable             | Standard  | Bedeutung                                                          |
|----------------------|-----------|--------------------------------------------------------------------|
| `BOOKS_DIR`          | –         | Quellordner mit den Büchern (wird nur gelesen)                     |
| `STATE_DB`           | –         | Pfad zur SQLite-Datenbank für den Verarbeitungsstand               |
| `MEILI_URL`          | –         | Adresse der Meilisearch-Instanz                                    |
| `MEILI_KEY`          | –         | Master-Key oder API-Key mit Schreibrechten                         |
| `MEILI_INDEX`        | `buecher` | Name des Index                                                     |
| `OCR_LANG`           | `deu`     | Sprache für die OCR                                                |
| `MIN_CHARS_PER_PAGE` | `50`      | Schwelle, ab der eine PDF als textbasiert gilt                     |
| `MAX_CHUNK_CHARS`    | `1500`    | Maximale Länge einer Passage                                       |
| `MEILI_TASK_TIMEOUT` | `3600`    | Wartezeit in Sekunden auf eine Meilisearch-Aufgabe                 |
| `EMBEDDER_URL`       | –         | OpenAI-kompatibler Endpunkt ohne `/embeddings`, z. B. `http://host:8090/v1` |
| `EMBEDDER_MODEL`     | –         | Modellname, wie ihn `<EMBEDDER_URL>/models` nennt                  |
| `EMBEDDER_DIMENSIONS`| –         | Dimension der Vektoren (optional, sonst ermittelt Meilisearch sie) |
| `EMBEDDER_API_KEY`   | –         | API-Key des Embedding-Servers (optional)                           |
| `EMBEDDER_NAME`      | `default` | Name des Embedders in Meilisearch                                  |
| `WORK_DIR`           | `<STATE_DB>.work` | Zwischenablage für extrahierte Passagen und Vektoren       |
| `EXTRACT_JOBS`       | `1`       | Zahl der Prozesse, die gleichzeitig Dateien extrahieren            |
| `EMBED_PARALLEL`     | `1`       | Zahl der gleichzeitigen Anfragen an den Embedding-Server           |
| `EMBED_BATCH_SIZE`   | `8`       | Zahl der Passagen pro Anfrage an den Embedding-Server              |
| `EMBED_TIMEOUT`      | `300`     | Zeitgrenze in Sekunden für eine Anfrage an den Embedding-Server    |

## Embeddings

Sind `EMBEDDER_URL` und `EMBEDDER_MODEL` gesetzt, berechnet buchindex zu jeder
Passage einen Vektor und schreibt ihn mit nach Meilisearch. Ohne die beiden
Variablen wird ohne Embeddings indexiert.

- **buchindex erzeugt die Vektoren selbst.** Es ruft `<EMBEDDER_URL>/embeddings`
  auf und liefert die Vektoren mit den Passagen aus (`_vectors` mit
  `regenerate: false`). Meilisearch bettet beim Indexieren nichts ein.
- **Meilisearch braucht den Endpunkt nur für Suchanfragen.** Beim Anlegen des
  Index wird derselbe Endpunkt als Embedder (Quelle `rest`) eingetragen, damit
  Meilisearch den Suchtext einbetten kann. Er muss dafür von der
  Meilisearch-Instanz aus erreichbar sein.
- **Interne Adressen freigeben.** Meilisearch blockiert Aufrufe an interne
  IP-Adressen (Fehler `bad uri: Rejected URI`). Liegt der Embedding-Server im
  eigenen Netz, braucht der Container zusätzlich z. B.
  `-e MEILI_EXPERIMENTAL_ALLOWED_IP_NETWORKS=192.168.178.82/32`
  (in `compose.yaml` über `MEILI_ALLOWED_IP_NETWORKS`).
- **Eingebettet wird** Titel, Kapitel und Text jeder Passage.
- **Suche:** semantisch bzw. hybrid über den Suchparameter
  `"hybrid": {"embedder": "default", "semanticRatio": 0.5}`.
- **Nachträglich einschalten:** Die Einstellungen werden nur beim Anlegen des
  Index gesetzt. Für einen bestehenden Index den Embedder einmalig über die
  Meilisearch-API setzen oder Index und `STATE_DB` löschen und neu aufbauen.

## Ressourcen

Drei Stellschrauben begrenzen, wie viel gleichzeitig läuft:

| Variable | Wirkt auf | Hinweis |
|---|---|---|
| `EXTRACT_JOBS` | CPU und Arbeitsspeicher des Rechners, auf dem buchindex läuft | Ein Prozess belegt schon knapp zwei Kerne. Richtwert: Zahl der echten Kerne geteilt durch zwei. |
| `EMBED_PARALLEL`, `EMBED_BATCH_SIZE` | Last auf dem Embedding-Server | Mehr gleichzeitige Anfragen helfen nur, wenn der Server sie auch gleichzeitig rechnen kann. |
| `MEILI_MAX_INDEXING_THREADS` (in `compose.yaml`) | Kerne, die Meilisearch beim Indexieren belegt | Meilisearch bettet nichts ein, der Bedarf ist klein. |

Die Extraktion läuft mit joblib in eigenen Prozessen, die Anfragen an den
Embedding-Server in Threads.

Messungen vom 12.11.2026:

- **Extraktion:** Auf einem Laptop mit zwei Kernen (vier Threads) brachten
  mehr Prozesse nichts: zehn Bücher mit rund 1100 Seiten brauchten mit einem
  Prozess 349 Sekunden, mit vier Prozessen 326 Sekunden. Auf einem Rechner
  mit mehr Kernen ist ein Gewinn zu erwarten, gemessen ist er nicht.
- **Einbetten:** Der getestete Server (llama.cpp, bge-m3, CPU) brauchte für
  acht Passagen immer rund zehn Sekunden, egal ob einzeln nacheinander, als
  eine Anfrage oder in vier parallelen Anfragen. `EMBED_PARALLEL=1` schont
  dort den Server, ohne Zeit zu kosten.

## Beispielaufrufe

```sh
uv run buchindex check            # Konfiguration, Systemprogramme, Meilisearch
uv run buchindex sync --dry-run   # zeigt, was verarbeitet würde
uv run buchindex sync             # vollständiger Ablauf
uv run buchindex status           # Dateien nach Status, letzte Fehler
```

`sync` endet mit Exit-Code 1, wenn mindestens eine Datei fehlgeschlagen ist.
Der Lauf selbst wird dadurch nicht abgebrochen; fehlerhafte Dateien werden beim
nächsten Lauf erneut versucht.

## Ablauf

1. `BOOKS_DIR` rekursiv nach `*.pdf` und `*.epub` durchsuchen.
2. Fingerprint (Dateigröße und mtime) mit der SQLite-Tabelle `files`
   abgleichen: neu, geändert, unverändert, entfernt.
3. **Stufe 1, Extraktion** aller neuen und geänderten Dateien, parallel mit
   `EXTRACT_JOBS` Prozessen:
   - PDF: Hat die Datei zu wenig Text, entsteht mit `ocrmypdf --skip-text` eine
     OCR-Kopie in einem temporären Verzeichnis. Das Original bleibt unverändert.
     Das Markdown wird seitenweise mit pymupdf4llm erzeugt.
   - EPUB: Konvertierung nach Markdown mit Pandoc.
   - ISBN suchen, Passagen bilden und in der Zwischenablage (`WORK_DIR`)
     speichern. Die Datei bekommt den Status `extrahiert`.
4. Danach Buch für Buch:
   - Metadaten bei Open Library abfragen (in SQLite gecacht).
   - **Stufe 2, Einbetten:** Vektoren der Passagen vom Embedding-Server holen
     und in der Zwischenablage speichern (nur mit Embedder).
   - **Stufe 3, Schreiben:** alte Passagen der Datei in Meilisearch löschen,
     neue schreiben. Die Datei bekommt den Status `ok`, ihre Zwischenablage
     wird geleert.
5. Passagen entfernter Dateien löschen.
6. Zusammenfassung loggen.

Scheitert eine spätere Stufe oder wird der Lauf abgebrochen, bleibt das
Ergebnis der früheren Stufen liegen. Der nächste Lauf setzt dort wieder an,
solange sich die Datei nicht geändert hat.

### Dokumentstruktur

| Feld              | Inhalt                                                        |
|-------------------|---------------------------------------------------------------|
| `id`              | stabiler Hash aus Dateipfad und laufender Nummer der Passage  |
| `buch_id`         | stabiler Hash aus dem Dateipfad                               |
| `datei`           | Pfad relativ zu `BOOKS_DIR`                                   |
| `titel`, `autor`  | von Open Library, sonst `null`                                |
| `isbn`            | gefundene ISBN ohne Trennzeichen, sonst `null`                |
| `kategorie`       | Liste: oberster Unterordner, sonst Themen von Open Library    |
| `kapitel`         | Überschriftenpfad, z. B. `Teil 1 > Kapitel 2`                 |
| `von_seite`, `bis_seite` | PDF-Seitenbereich (ab 1), bei EPUB `null`              |
| `pdf_seite`       | wie `von_seite`, zum Sortieren                                |
| `gedruckte_seite` | immer `null` (wird in dieser Version nicht erkannt)           |
| `text`            | Text der Passage (Markdown)                                   |

Index-Einstellungen (werden gesetzt, wenn der Index angelegt wird):
filterbar `buch_id`, `autor`, `kategorie`, `kapitel`; sortierbar `pdf_seite`;
durchsuchbar `text`, `titel`, `kapitel`.

## Tests

```sh
uv run pytest
uv run ruff check
```

- Meilisearch und HTTP sind gemockt; ein Fixture sperrt Netzwerkzugriffe.
- Der Integrationstest läuft nur, wenn `MEILI_URL` (und `MEILI_KEY`) in der
  Umgebung gesetzt sind. Er legt einen eigenen Testindex an und löscht ihn.
  Die `.env` wird von den Tests nicht gelesen.
- EPUB- und OCR-Tests laufen nur, wenn pandoc bzw. tesseract vorhanden sind.

## Annahmen

Wo die Spezifikation offen war, gelten diese Entscheidungen:

- **Systemprüfung:** Sie läuft vor jedem Befehl, auch vor `status` und
  `sync --dry-run`. Nur `check` bricht nicht sofort ab, sondern listet fehlende
  Programme zusammen mit den übrigen Prüfungen auf.
- **Pfade:** `datei` und der Schlüssel `pfad` in SQLite sind relativ zu
  `BOOKS_DIR`. So bleiben IDs gleich, wenn der Ordner im Container an anderer
  Stelle gemountet wird.
- **Textschwelle:** Verglichen wird der Durchschnitt der Zeichen pro Seite über
  die ganze PDF. Die eingebaute OCR von pymupdf4llm ist abgeschaltet, OCR läuft
  nur über ocrmypdf.
- **Zusätzliche Felder:** `pdf_seite` und `gedruckte_seite` stehen nicht in der
  Liste der Dokumentfelder, werden aber an anderer Stelle vorausgesetzt
  (sortierbares Attribut bzw. „das Feld bleibt leer“).
- **Kategorie:** Liegt die Datei in einem Unterordner von `BOOKS_DIR`, ist der
  oberste Ordnername die Kategorie. Sonst werden die Themen (`subjects`) von
  Open Library übernommen, unverändert und ohne Dubletten. `kategorie` ist
  deshalb immer eine Liste und kann leer sein.
- **Kapitel:** `kapitel` enthält den Pfad der Überschriften-Hierarchie. Die
  Überschrift selbst steht nicht zusätzlich im `text`. Markdown- und
  HTML-Auszeichnung wird aus dem Kapitelnamen entfernt. Bei PDFs leitet
  pymupdf4llm die Ebenen aus dem Layout ab, das kann ungenau sein.
- **Textbereinigung bei PDFs:** Kolumnentitel und Seitenzahlen (Kopf- und
  Fußzeilen) werden nicht übernommen. Die Markierungen, die pymupdf4llm um
  Text aus Abbildungen und Formeln setzt, werden entfernt.
- **Passagen:** Seitenumbrüche gelten als Absatzgrenzen. Ein einzelner Absatz
  über `MAX_CHUNK_CHARS` wird an Leerzeichen geteilt, damit das Limit immer
  hält.
- **Alte Passagen löschen:** über den Filter `buch_id = "…"`.
- **ISBN:** Nur Nummern mit gültiger Prüfziffer zählen. Eine ISBN-13 hat Vorrang
  vor einer ISBN-10. Bei EPUBs (keine Seiten) werden die ersten 10 000 Zeichen
  durchsucht.
- **Open Library:** Autoren und Themen stehen oft nur am Werk, nicht an der
  Ausgabe. Deshalb wird zusätzlich `/works/<ID>.json` und je Autor
  `/authors/<ID>.json` abgefragt. Mehrere Autoren
  stehen kommagetrennt in `autor`. Unbekannte ISBNs (404) werden als „keine
  Metadaten“ gecacht. Netzwerk- und Serverfehler werden nicht gecacht: Die Datei
  bekommt den Status `fehler` und wird beim nächsten Lauf erneut versucht.
- **Fehlerhafte Dateien** zählen beim nächsten Lauf als „geändert“, ebenso
  Dateien, die nach der Extraktion noch nicht im Index angekommen sind
  (Status `extrahiert`).
- **Drei Stufen, ein Befehl:** Extraktion, Einbetten und Schreiben sind
  getrennte Stufen mit gespeicherten Zwischenergebnissen, laufen aber weiter
  über `buchindex sync`. Eigene Befehle je Stufe gibt es nicht.
- **Zwischenablage:** Ohne `WORK_DIR` liegt sie neben der Datenbank
  (`<STATE_DB>.work`). Vektoren werden pro Buch gespeichert; bricht das
  Einbetten mitten im Buch ab, beginnt es für dieses Buch von vorn.
- **Embedding-Text:** Titel, Kapitel und Text, begrenzt auf
  `4 × MAX_CHUNK_CHARS + 1000` Zeichen.
- **`check`** schickt bei konfiguriertem Embedder einen kurzen Testtext an den
  Embedding-Server.
- **Index-Einstellungen** werden nur beim Anlegen des Index gesetzt. Spätere
  Änderungen an `IndexSettings` wirken erst nach dem Löschen des Index.
- **`--dry-run`** legt die SQLite-Datei an, falls sie fehlt, schreibt aber
  keinen Verarbeitungsstand.

## Docker

`Dockerfile` und `compose.yaml` bringen buchindex und Meilisearch auf den
Server. Im Image sind alle Systemprogramme enthalten. Auf dem Server selbst
braucht es nur Docker mit dem Compose-Plugin und `openssl` (für den Key;
`apt install openssl`).

Die Einrichtung kann ein Agent auf dem Server übernehmen: Der Prompt dafür
steht in [`deploy/server-prompt.md`](deploy/server-prompt.md) (Ordner anlegen,
Repository klonen oder aktualisieren, `.env` mit Key erzeugen, Image bauen,
prüfen). Von Hand sind es diese Schritte:

1. Ordner anlegen (`mkdir -p ~/books`) und Bücher auf den Server kopieren, z. B.
   `rsync -a --delete ~/Dokumente/ server:books/`. `-a` erhält die
   Änderungszeiten, an denen buchindex Änderungen erkennt.
2. `.env` neben `compose.yaml` anlegen (Vorlage: `.env.example`). `BOOKS_DIR`
   steht dort auf `${HOME}/books`; liegt der Ordner woanders, anpassen. Für Embeddings kommen
   `EMBEDDER_*` und `MEILI_ALLOWED_IP_NETWORKS` dazu. Den Master-Key für
   Meilisearch direkt auf dem Server erzeugen und eintragen:

   ```sh
   cp .env.example .env
   sed -i "s/^MEILI_KEY=.*/MEILI_KEY=$(openssl rand -hex 32)/" .env
   chmod 600 .env
   ```

   Der Key gilt ab dem ersten Start von Meilisearch. Wer ihn später ändert,
   muss Meilisearch neu starten.
3. Starten:

```sh
docker compose up -d                        # Meilisearch
docker compose run --rm buchindex check     # Konfiguration prüfen
docker compose run --rm buchindex           # Lauf (sync)
docker compose run --rm buchindex status
```

- `BOOKS_DIR` wird read-only nach `/books` gemountet. Datenbank und
  Zwischenablage liegen im Volume `buchindex_data`, der Index im Volume
  `meili_data`.
- `BOOKS_DIR`, `STATE_DB`, `WORK_DIR` und `MEILI_URL` setzt `compose.yaml` für
  den Container selbst; die übrigen Werte kommen aus der `.env`.
- Der Container läuft als Benutzer mit der UID 1000 und muss die Bücher lesen
  können. Eine andere UID setzt `docker compose build --build-arg UID=…`.
- Meilisearch ist nur auf dem Server selbst erreichbar (`127.0.0.1:7700`).
  `MEILI_BIND=0.0.0.0:7700` in der `.env` öffnet es für das Netz.
- OCR-Kopien liegen im temporären Verzeichnis des Containers.

Nächtlicher Lauf per cron auf dem Server; `flock` verhindert, dass ein neuer
Lauf startet, solange der vorige noch arbeitet:

```
0 2 * * * cd /pfad/zu/buchindex && flock -n /tmp/buchindex.lock docker compose run --rm -T buchindex
```

## Erfahrungen mit echten Büchern

Stand 11.11.2026, Stichprobe von 18 Dateien aus einem Bestand von 822
(767 PDF, 55 EPUB, rund 149 000 Seiten):

- **Mehrspaltige Seiten** (zwei- und dreispaltig) werden in der richtigen
  Lesereihenfolge extrahiert. Im Bestand sind das fast nur Paper (etwa 25
  Dateien).
- **Geschwindigkeit:** etwa 2 bis 3 Seiten pro Sekunde auf einem Laptop mit
  vier Kernen. Der erste Lauf über den ganzen Bestand dauert damit grob
  15 bis 20 Stunden. Spätere Läufe verarbeiten nur Neues.
- **Mit Embeddings** (bge-m3 auf einem llama.cpp-Server, Messung vom
  12.11.2026 an einem Buch mit 851 Seiten und 1602 Passagen): 5 Minuten
  Extraktion, 37 Minuten Einbetten, also rund 1,4 Sekunden pro Passage und
  knapp 3 Sekunden pro Seite insgesamt. Hochgerechnet auf den Bestand sind das
  grob fünf Tage für den ersten Lauf.
  Das Einbetten bestimmt die Dauer; schnellere Extraktion ändert daran wenig.
- **OCR** wurde für 11 PDFs des Bestands nötig. Der erkannte Text ist
  brauchbar, enthält bei Foliensätzen aber Reste von Symbolen und Bedienelementen.
- **ISBN:** Bei etwa 45 % der PDFs steht eine ISBN auf den ersten fünf Seiten.
  Open Library kennt davon nur einen Teil (viele kostenlose Verlagsreports
  fehlen). Bei Papern gehört die ISBN zum Tagungsband, der Titel ist dann der
  des Bandes und nicht der des Papers.
- **Kapitel:** Der Buchtitel landet oft als oberste Überschrift im Pfad. Einzelne
  Bücher haben gesperrt gesetzte Überschriften (`I N T R O D U C T I O N`) oder
  falsch erkannte Überschriften.
- **Sehr kurze Passagen** (unter 100 Zeichen, etwa 3 %) entstehen aus
  Abschnitten, die fast nur aus einer Überschrift bestehen, und aus
  Foliennummern.
- **Leere Dateien** (0 Byte) werden als Fehler vermerkt und bei jedem Lauf
  erneut versucht.

## Offene Punkte

- Erkennung gedruckter Seitenzahlen
- Sehr kurze Passagen zusammenlegen
- Dubletten im Bestand (gleiche Datei unter mehreren Namen)
