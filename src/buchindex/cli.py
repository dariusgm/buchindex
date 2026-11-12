"""Kommandozeile für buchindex."""

from __future__ import annotations

import logging

import typer
from dotenv import find_dotenv, load_dotenv

from buchindex import pipeline
from buchindex.config import ConfigError, Settings
from buchindex.embedding import EmbeddingClient
from buchindex.metadata import MetadataClient
from buchindex.search import SearchIndex
from buchindex.state import StateDB
from buchindex.systemcheck import MissingProgramsError, ensure_programs, find_missing_programs

app = typer.Typer(
    help="Indexiert PDF- und EPUB-Bücher in Meilisearch.",
    no_args_is_help=True,
    add_completion=False,
)

_SYNC_VARS = ("BOOKS_DIR", "STATE_DB", "MEILI_URL", "MEILI_KEY")


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=1)


def _embedder(settings: Settings) -> EmbeddingClient | None:
    if not settings.embedder_url:
        return None
    return EmbeddingClient(
        settings.embedder_url,
        settings.embedder_model,
        settings.embedder_api_key,
        settings.embedder_dimensions,
        settings.embed_parallel,
        settings.embed_batch_size,
        settings.embed_timeout,
    )


def _settings(*required: str) -> Settings:
    try:
        settings = Settings.from_env()
        settings.require(*required)
    except ConfigError as error:
        raise _fail(f"Konfigurationsfehler: {error}") from None
    return settings


@app.callback()
def main(ctx: typer.Context) -> None:
    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # `check` meldet fehlende Programme selbst, zusammen mit den übrigen Prüfungen.
    if ctx.invoked_subcommand != "check":
        try:
            ensure_programs()
        except MissingProgramsError as error:
            raise _fail(str(error)) from None


@app.command()
def sync(
    dry_run: bool = typer.Option(False, "--dry-run", help="Nur anzeigen, was verarbeitet würde."),
) -> None:
    """Führt den vollständigen Ablauf aus."""
    if dry_run:
        settings = _settings("BOOKS_DIR", "STATE_DB")
        with StateDB(settings.state_db) as state:
            _, changes = pipeline.plan(settings, state)
        for label, pfade in (
            ("neu", changes.neu),
            ("geändert", changes.geaendert),
            ("entfernt", changes.entfernt),
        ):
            for pfad in pfade:
                typer.echo(f"{label}: {pfad}")
        typer.echo(
            f"Würde verarbeiten: {len(changes.neu)} neu, {len(changes.geaendert)} geändert, "
            f"{len(changes.entfernt)} entfernt, {len(changes.unveraendert)} unverändert."
        )
        return

    settings = _settings(*_SYNC_VARS)
    index = SearchIndex.connect(
        settings.meili_url,
        settings.meili_key,
        settings.meili_index,
        settings.index_settings,
        settings.meili_task_timeout,
    )
    with StateDB(settings.state_db) as state:
        try:
            summary = pipeline.sync(
                settings, state, index, MetadataClient(state), _embedder(settings)
            )
        except Exception as error:
            raise _fail(f"Lauf abgebrochen: {error}") from error
    typer.echo(
        f"Fertig: {summary.neu} neu, {summary.geaendert} geändert, "
        f"{summary.uebersprungen} übersprungen, {summary.entfernt} entfernt, "
        f"{summary.fehler} Fehler."
    )
    if summary.fehler:
        raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """Zeigt die Anzahl der Dateien nach Status und die letzten Fehler."""
    settings = _settings("STATE_DB")
    with StateDB(settings.state_db) as state:
        counts = state.status_counts()
        errors = state.last_errors()
    if not counts:
        typer.echo("Noch keine Dateien verarbeitet.")
    for name, count in sorted(counts.items()):
        typer.echo(f"{name}: {count}")
    if errors:
        typer.echo("Letzte Fehler:")
        for pfad, zeitpunkt, fehler in errors:
            typer.echo(f"  {zeitpunkt}  {pfad}: {fehler}")


@app.command()
def check() -> None:
    """Prüft Konfiguration, Systemprogramme und Meilisearch-Erreichbarkeit."""
    ok = True

    def report(passed: bool, text: str) -> None:
        nonlocal ok
        ok = ok and passed
        typer.echo(f"[{'ok' if passed else 'FEHLER'}] {text}")

    settings = None
    try:
        settings = Settings.from_env()
        settings.require(*_SYNC_VARS)
        report(True, "Konfiguration vollständig")
    except ConfigError as error:
        report(False, f"Konfiguration: {error}")

    missing = find_missing_programs()
    for program in missing:
        report(
            False,
            f"{program.command} fehlt im PATH: `apt install {program.apt}` "
            f"bzw. `brew install {program.brew}`",
        )
    if not missing:
        report(True, "Systemprogramme vorhanden")

    if settings is None or settings.missing("MEILI_URL", "MEILI_KEY"):
        report(False, "Meilisearch: nicht geprüft, MEILI_URL oder MEILI_KEY fehlt")
    else:
        try:
            SearchIndex.connect(
                settings.meili_url,
                settings.meili_key,
                settings.meili_index,
                settings.index_settings,
            ).check()
            report(True, f"Meilisearch erreichbar, Key gültig ({settings.meili_url})")
        except Exception as error:
            report(False, f"Meilisearch ({settings.meili_url}): {error}")

    if settings is not None and settings.embedder_url:
        try:
            _embedder(settings).embed(["Test"])
            report(True, f"Embedding-Server erreichbar ({settings.embedder_url})")
        except Exception as error:
            report(False, f"Embedding-Server ({settings.embedder_url}): {error}")

    if not ok:
        raise typer.Exit(code=1)
