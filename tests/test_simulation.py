"""Integration test for the full end-to-end data simulation pipeline."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.simulate_pipeline import run_simulation


def test_end_to_end_simulation_pipeline():
    """Exercise authenticated HTTP, booking, views, Redis, Neo4j, and cleanup."""
    assert run_simulation(keep=False) is True

