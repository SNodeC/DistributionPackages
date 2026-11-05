"""Workflow-dispatch workers; selection and scheduling belong to core-ci."""

from pathlib import Path
import sys

# Existing helpers use sibling imports. Keep one import location, unchanged.
LEGACY = Path(__file__).resolve().parents[1] / "core_ci"
sys.path.insert(0, str(LEGACY))
