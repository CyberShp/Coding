"""Shared fixtures for observation_points tests."""
import sys
from pathlib import Path

# Ensure the parent of observation_points is on path so 'observation_points' is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
