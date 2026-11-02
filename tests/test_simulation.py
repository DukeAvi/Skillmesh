"""Integration test for the full end-to-end data simulation pipeline."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.simulate_pipeline import run_simulation


def test_end_to_end_simulation_pipeline():
    """Run all 16 stages of the simulation pipeline:
    - Baseline recording and restoration
    - User/skill onboarding & vector embeddings
    - Profile metadata verification (/api/users with email & department)
    - Catalogue search & client filtering simulation
    - View 2 (`skill_popularity`) demand gap validation
    - Matchmaker endpoint (/api/matches) with ratings
    - HTTP POST /api/requests creation and validation (201, 400, 422)
    - Exchange log endpoint (/api/requests?user_id=...)
    - Pessimistic locking concurrency race test (`SELECT ... FOR UPDATE`)
    - Procedure 2 (`sp_complete_swap_session`) and idempotency guard
    - Feedback & rating computation (`fn_provider_average_rating`)
    - Dynamic views live updates (`leaderboard` and `skill_popularity`)
    - Redis ephemeral presence lifecycle
    - Neo4j graph synchronization (TEACHES, WANTS, MENTORS)
    - Web Observatory API payload checks
    - Pristine baseline restoration
    """
    assert run_simulation(keep=False) is True

