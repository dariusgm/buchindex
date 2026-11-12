FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

# Systemprogramme für OCR (tesseract, ghostscript, qpdf) und EPUB (pandoc)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-deu ghostscript qpdf pandoc \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Erst nur die Abhängigkeiten, damit diese Schicht bei Codeänderungen erhalten bleibt
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Läuft ohne root. /data nimmt Datenbank und Zwischenablage auf, /books die Bücher.
ARG UID=1000
RUN useradd --create-home --uid ${UID} buchindex \
    && mkdir /data /books \
    && chown buchindex /data
USER buchindex

ENV PATH="/app/.venv/bin:${PATH}" \
    BOOKS_DIR=/books \
    STATE_DB=/data/state.db

VOLUME /data
ENTRYPOINT ["buchindex"]
CMD ["sync"]
