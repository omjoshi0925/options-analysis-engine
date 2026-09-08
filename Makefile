# Common developer tasks. Every target uses the local virtual environment.
PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
STAMP := $(shell date +%Y%m%d-%H%M%S)

.PHONY: help venv install test lint demo app status clean

help:
	@echo "make venv     create $(VENV) and install the package with the app and dev extras"
	@echo "make install  reinstall dependencies into an existing $(VENV)"
	@echo "make test     run the test suite"
	@echo "make lint     run ruff"
	@echo "make demo     run the offline synthetic demonstration into results/demo-<timestamp>"
	@echo "make app      launch the Streamlit dashboard"
	@echo "make status   show collector and training status for config/collector.json"
	@echo "make clean    remove caches and build artifacts; data and results are kept"

venv: $(BIN)/python

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -r requirements.txt

install: venv
	$(BIN)/python -m pip install -r requirements.txt

test: venv
	$(BIN)/python -m pytest -q

lint: venv
	$(BIN)/ruff check .

demo: venv
	$(BIN)/python -m options_engine demo --output results/demo-$(STAMP)

app: venv
	$(BIN)/python -m streamlit run BSM_streamlit.py

status: venv
	$(BIN)/python -m options_engine status --config config/collector.json

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
