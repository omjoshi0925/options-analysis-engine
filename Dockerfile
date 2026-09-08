# Options Analysis Engine: one image for the dashboard and the collector.
#
#   docker build -t options-analysis-engine .
#   docker run --rm -p 8501:8501 options-analysis-engine dashboard
#   docker run --rm -e TRADIER_TOKEN -v "$PWD/config:/app/config:ro" -v engine-data:/app/data \
#       options-analysis-engine collect --config config/collector.json
#
# The collector's default data_root (../data/live relative to the config file) resolves to
# /app/data/live, so mount a volume there to keep snapshots, the ledger, and models.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml LICENSE.txt README.md ./
COPY options_engine ./options_engine
COPY BSM_streamlit.py ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[app]" \
    && useradd --create-home --uid 1000 engine \
    && mkdir -p /app/data /app/config \
    && chown -R engine:engine /app

USER engine
EXPOSE 8501
ENTRYPOINT ["entrypoint"]
CMD ["--help"]
