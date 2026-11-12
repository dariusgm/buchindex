import pytest

from buchindex.config import ConfigError, IndexSettings, Settings


def test_defaults():
    settings = Settings.from_env({})
    assert settings.meili_index == "buecher"
    assert settings.ocr_lang == "deu"
    assert settings.min_chars_per_page == 50
    assert settings.max_chunk_chars == 1500
    assert settings.books_dir is None


def test_values_from_env(tmp_path):
    settings = Settings.from_env(
        {"BOOKS_DIR": str(tmp_path), "MEILI_INDEX": "test", "MAX_CHUNK_CHARS": "800"}
    )
    assert settings.books_dir == tmp_path
    assert settings.meili_index == "test"
    assert settings.max_chunk_chars == 800


def test_invalid_number():
    with pytest.raises(ConfigError, match="MIN_CHARS_PER_PAGE"):
        Settings.from_env({"MIN_CHARS_PER_PAGE": "viele"})


def test_require_names_missing_variables(tmp_path):
    settings = Settings.from_env({"BOOKS_DIR": str(tmp_path)})
    with pytest.raises(ConfigError, match="STATE_DB, MEILI_URL"):
        settings.require("BOOKS_DIR", "STATE_DB", "MEILI_URL")


def test_require_books_dir_must_exist(tmp_path):
    settings = Settings.from_env({"BOOKS_DIR": str(tmp_path / "fehlt")})
    with pytest.raises(ConfigError, match="kein Verzeichnis"):
        settings.require("BOOKS_DIR")


def test_index_settings_without_embedder():
    meili = IndexSettings().to_meili()
    assert meili == {
        "filterableAttributes": ["buch_id", "autor", "kategorie", "kapitel"],
        "sortableAttributes": ["pdf_seite"],
        "searchableAttributes": ["text", "titel", "kapitel"],
    }


def test_index_settings_with_embedder():
    meili = IndexSettings(embedders={"default": {"source": "ollama"}}).to_meili()
    assert meili["embedders"] == {"default": {"source": "ollama"}}


def test_no_embedder_by_default():
    assert Settings.from_env({}).index_settings.embedders == {}


def test_embedder_from_env():
    settings = Settings.from_env(
        {
            "EMBEDDER_URL": "http://embed.invalid:8090/v1/",
            "EMBEDDER_MODEL": "bge-m3",
            "EMBEDDER_DIMENSIONS": "1024",
            "MAX_CHUNK_CHARS": "1000",
        }
    )
    embedder = settings.index_settings.to_meili()["embedders"]["default"]
    assert embedder["source"] == "rest"
    assert embedder["url"] == "http://embed.invalid:8090/v1/embeddings"
    assert embedder["request"] == {"model": "bge-m3", "input": ["{{text}}", "{{..}}"]}
    assert embedder["dimensions"] == 1024
    assert embedder["documentTemplateMaxBytes"] == 5000
    assert "{{ doc.text }}" in embedder["documentTemplate"]
    assert "apiKey" not in embedder


def test_embedder_api_key_and_name():
    settings = Settings.from_env(
        {
            "EMBEDDER_URL": "http://embed.invalid/v1",
            "EMBEDDER_MODEL": "m",
            "EMBEDDER_API_KEY": "geheim",
            "EMBEDDER_NAME": "bge",
        }
    )
    assert settings.index_settings.embedders["bge"]["apiKey"] == "geheim"
    assert "dimensions" not in settings.index_settings.embedders["bge"]


def test_embedder_needs_url_and_model():
    with pytest.raises(ConfigError, match="EMBEDDER_MODEL"):
        Settings.from_env({"EMBEDDER_URL": "http://embed.invalid/v1"})


def test_resource_settings(tmp_path):
    settings = Settings.from_env({"STATE_DB": str(tmp_path / "state.db")})
    assert (settings.extract_jobs, settings.embed_parallel, settings.embed_batch_size) == (1, 1, 8)
    assert settings.work_path == tmp_path / "state.db.work"

    settings = Settings.from_env(
        {
            "STATE_DB": str(tmp_path / "state.db"),
            "WORK_DIR": str(tmp_path / "arbeit"),
            "EXTRACT_JOBS": "4",
            "EMBED_PARALLEL": "2",
            "EMBED_BATCH_SIZE": "16",
            "EMBED_TIMEOUT": "60",
        }
    )
    assert settings.work_path == tmp_path / "arbeit"
    assert (settings.extract_jobs, settings.embed_parallel) == (4, 2)
    assert (settings.embed_batch_size, settings.embed_timeout) == (16, 60)
    with pytest.raises(ConfigError, match="EXTRACT_JOBS"):
        Settings.from_env({"EXTRACT_JOBS": "0"})
