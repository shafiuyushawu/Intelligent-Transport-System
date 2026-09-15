# Intelligent Transport System Simulation Project

This project reproduces a traffic-congestion control study in Eclipse SUMO using Python and TraCI. It is a methodological replication of the paper by Huang, Weng, Wu, and Chen, focusing on how control policies affect congestion under simulated demand patterns and network conditions.

The implementation is designed to be reproducible, configurable, and compatible with a local SUMO installation on macOS or Linux-based systems.

## Project goal

The repository reconstructs the study workflow in SUMO by:

- generating a synthetic road network and traffic signal plans
- creating vehicle routes and congestion scenarios
- comparing multiple control policies
- aggregating simulation results into summary tables and plots
- validating the environment and outputs with automated checks

This is a replication study, not a direct numerical recreation of a proprietary VISSIM implementation.

## Repository structure

- `config/` - experiment configuration files
- `docs/` - methodology, assumptions, policy mapping, and notes
- `network/` - source XML, generated SUMO network, and metadata
- `routes/` - route generation artifacts and summaries
- `policies/` - policy implementations
- `simulation/` - traffic simulation logic, runners, and batch execution
- `analysis/` - aggregation and plotting scripts
- `results/` - raw, processed, and visual outputs
- `scripts/` - command-line entry points for generation and reproduction
- `tests/` - project validation tests

## Prerequisites

Before running the project, install the following:

- Python 3.10+
- Eclipse SUMO 1.27.1
- `make`
- `pip`

On macOS, you may also need XQuartz if you want to run the SUMO GUI.

## Install and set up

Clone the project and move into the repository directory:

```bash
git clone <project-url>
cd "Intelligent Transport System"
```

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
make setup
```

Set the SUMO environment variable so the project can find the SUMO tools:

```bash
export SUMO_HOME="/path/to/sumo"
```

Example macOS installation:

```bash
export SUMO_HOME="/Applications/SUMO"
```

If your SUMO installation is elsewhere, replace the path accordingly. The project checks this variable during validation and uses it to locate `sumo`, `netconvert`, and related tools.

## Validate the environment

To verify the project can find SUMO and the required Python dependencies:

```bash
make smoke-test
```

You can also run:

```bash
python3 scripts/validate_project.py --headless
```

## Run a single simulation

You can run one simulation using a specific policy, demand level, and random seed:

```bash
python3 -m simulation.runner --policy huang --demand heavy --seed 42 --gui false
```

This runs a single experiment and writes outputs under `results/`.

## Run the full experiment matrix

The project includes a full matrix of experiments across policies, demand levels, and seeds:

```bash
make experiments
```

This executes:

- 3 policies: `normal`, `long`, `huang`
- 3 demand levels: `low`, `medium`, `heavy`
- 5 seeds: `11`, `22`, `33`, `44`, `55`

## Run the full reproduction pipeline

To execute the complete workflow from validation through network generation, route generation, experiment execution, aggregation, and plotting:

```bash
make reproduce
```

This is the main command for a full study run.

## Run the short demo

For a lightweight demonstration run intended for a presentation or quick validation:

```bash
make reproduce-short
```

This uses a smaller configuration and writes results to `results/demo`.

## Generate specific components manually

If you want to run stages separately:

```bash
make network
make routes
make experiments
make analysis
```

You can also run the scripts directly if needed:

```bash
python3 scripts/generate_network.py
python3 scripts/generate_routes.py
python3 scripts/run_experiments.py
python3 scripts/aggregate_results.py
```

## Open the GUI

To open the SUMO GUI for visual inspection:

```bash
make gui
```

On macOS, ensure XQuartz is running. If the GUI appears blank, try:

```bash
defaults write org.xquartz.X11 enable_iglx -bool true
export DISPLAY=:0.0
```

## Testing

Run the test suite:

```bash
make test
```

The tests cover environment configuration, route generation, signal logic, congestion behavior, and reproducibility checks.

## Output folders

Simulation results are written to subfolders under `results/`, including:

- `results/raw/` - raw simulation outputs
- `results/processed/` - aggregated CSV and JSON tables
- `results/figures/` - charts and plots
- `results/logs/` - logs and execution information

## Assumptions and methodology

This project follows a documented replication approach with explicit assumptions. See the documentation in `docs/` for the methodology, assumptions, and policy mapping used to reconstruct the scenario.

The code is organized to make each stage traceable:

1. environment and scaffold setup
2. network generation
3. traffic signal generation
4. route creation
5. congestion control logic
6. policy comparison
7. analysis and replication validation

## Citation

```text
Huang, Y.-S., Weng, Y.-S., Wu, W., & Chen, B.-Y. (2016).
Control strategies for solving the problem of traffic congestion.
IET Intelligent Transport Systems.
DOI: 10.1049/iet-its.2016.0003
```

## Quick start summary

```bash
python3 -m venv .venv
source .venv/bin/activate
export SUMO_HOME="/path/to/sumo"
make setup
make smoke-test
make reproduce
```

If you want, I can also help tailor this README for a university coursework submission or convert it into a more polished GitHub-style version with badges and screenshots.
# Intelligent-Transport-System
