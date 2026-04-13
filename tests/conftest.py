"""Shared test configuration for sim tests."""
from pathlib import Path

# Root fixtures directory — all tests reference this
FIXTURES = Path(__file__).parent / "fixtures"
EXECUTION = Path(__file__).parent / "execution"
