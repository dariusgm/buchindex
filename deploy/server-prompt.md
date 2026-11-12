# Prompt: buchindex auf dem Server einrichten

Dieser Text ist für den Agenten gedacht, der den Server verwaltet. Er richtet
buchindex neben den bestehenden Diensten ein oder bringt es auf den neuesten
Stand. Den Abschnitt unter der Linie unverändert übergeben.

---

Richte auf diesem Server das Projekt „buchindex" ein oder aktualisiere es. Es
indexiert die Bücher aus `~/books` in eine eigene Meilisearch-Instanz. Das
Image wird hier auf dem Server gebaut, es gibt keines in einer Registry.

Der Vorgang muss wiederholbar sein: Ein zweiter Durchlauf darf nichts
kaputtmachen und nur nachziehen, was sich geändert hat.

## Schritte

1. **Voraussetzungen prüfen:** `git`, `docker compose` und `openssl` müssen
   vorhanden sein. Fehlt etwas, nenne es und höre auf; installiere nichts
   ungefragt.
2. **Bücherordner anlegen:** `mkdir -p ~/books`. Der Ordner wird später per
   rsync vom Laptop gefüllt. Ändere oder lösche nichts darin.
3. **Repository holen:**
   - Gibt es `~/buchindex` noch nicht:
     `git clone https://github.com/dariusgm/buchindex.git ~/buchindex`
   - Sonst: `git -C ~/buchindex pull --ff-only`. Scheitert das, weil es lokale
     Änderungen gibt, verwirf sie nicht, sondern berichte.
4. **`.env` anlegen, falls sie fehlt:** in `~/buchindex`

   ```sh
   cp .env.example .env
   sed -i "s/^MEILI_KEY=.*/MEILI_KEY=$(openssl rand -hex 32)/" .env
   chmod 600 .env
   ```

   Trage außerdem diese Werte ein:

   ```
   EMBEDDER_URL=http://192.168.178.82:8090/v1
   EMBEDDER_MODEL=/models/bge-m3-Q8_0.gguf
   EMBEDDER_DIMENSIONS=1024
   MEILI_ALLOWED_IP_NETWORKS=192.168.178.82/32
   ```

   `BOOKS_DIR` steht in der Vorlage schon auf `${HOME}/books`. Setze
   `EXTRACT_JOBS` auf die halbe Zahl der echten CPU-Kerne, mindestens 1.

   Gibt es die `.env` schon, lass sie unverändert. Insbesondere darf
   `MEILI_KEY` nie neu erzeugt werden, sonst passt er nicht mehr zum
   vorhandenen Index. Gib den Key nirgends aus, auch nicht im Bericht.
5. **Port prüfen:** Meilisearch belegt `127.0.0.1:7700`. Ist der Port schon
   vergeben, wähle einen freien und trage ihn als `MEILI_BIND=127.0.0.1:<port>`
   in die `.env` ein.
6. **Image bauen:** in `~/buchindex`

   ```sh
   docker compose build --build-arg UID="$(id -u)" buchindex
   ```

7. **Meilisearch starten und prüfen:**

   ```sh
   docker compose up -d
   docker compose run --rm buchindex check
   ```

   Alle Zeilen von `check` müssen mit `[ok]` beginnen.

## Grenzen

- Starte **keinen** `sync`. Der erste Lauf dauert mehrere Tage und wird von
  Hand angestoßen, sobald die Bücher kopiert sind.
- Richte keinen cron-Eintrag ein.
- Fasse keine anderen Container, Volumes, Netzwerke oder Compose-Projekte an.
- Lösche keine Volumes (`meili_data`, `buchindex_data`); darin liegen Index
  und Verarbeitungsstand.

## Bericht

Nenne am Ende: den Commit, auf dem `~/buchindex` steht, ob die `.env` neu
angelegt wurde, den Port von Meilisearch, den gewählten Wert für
`EXTRACT_JOBS`, die Ausgabe von `check` und alles, was nicht geklappt hat.
