"""Shared fixtures for observation_points tests."""
import sys
from pathlib import Path

# Ensure the agent package is importable (observation_web/ on sys.path)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Create 'observation_points' alias so legacy imports still work
import agent  # noqa: E402
sys.modules['observation_points'] = agent

import agent.core  # noqa: E402
sys.modules['observation_points.core'] = agent.core

import agent.core.base  # noqa: E402
sys.modules['observation_points.core.base'] = agent.core.base

import agent.utils  # noqa: E402
sys.modules['observation_points.utils'] = agent.utils

import agent.utils.helpers  # noqa: E402
sys.modules['observation_points.utils.helpers'] = agent.utils.helpers

import agent.observers  # noqa: E402
sys.modules['observation_points.observers'] = agent.observers
