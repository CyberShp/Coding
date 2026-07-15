"""Shared fixtures for observation_points tests."""
import sys
from pathlib import Path

# Tests run directly against the source package in ``agent``.
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))
