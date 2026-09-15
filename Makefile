SHELL := /bin/zsh
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup test smoke-test validate network routes congestion experiments analysis reproduce reproduce-short gui

setup:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest

smoke-test:
	$(PYTHON) scripts/validate_project.py --headless

network:
	$(PYTHON) scripts/generate_network.py

routes:
	$(PYTHON) scripts/generate_routes.py

congestion:
	$(PYTHON) scripts/run_congestion.py

experiments:
	$(PYTHON) scripts/run_experiments.py

analysis:
	$(PYTHON) scripts/aggregate_results.py

reproduce:
	$(PYTHON) scripts/reproduce_all.py

reproduce-short:
	$(PYTHON) scripts/reproduce_all.py --demo --skip-tests --policies normal long huang --demand-levels low --seeds 11 --max-simulation-time 600 --max-wall-clock-seconds 120 --output-dir results/demo

validate:
	$(PYTHON) scripts/validate_project.py --headless

gui:
	$(PYTHON) scripts/view_gui.py
