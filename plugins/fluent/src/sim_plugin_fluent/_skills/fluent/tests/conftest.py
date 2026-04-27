"""Shared fixtures for Fluent integration tests."""
import os
import pytest


def pytest_addoption(parser):
    parser.addoption("--sim-host", default=None, help="sim-server host (e.g. 100.90.110.79)")
    parser.addoption("--sim-port", default=7600, type=int, help="sim-server port")
    # Default to $SIM_DATASETS/mixing_elbow.msh.h5; override with --mesh-file.
    _datasets = os.environ.get("SIM_DATASETS", "")
    _default_mesh = os.path.join(_datasets, "mixing_elbow.msh.h5") if _datasets else None
    parser.addoption("--mesh-file", default=_default_mesh,
                     help="Path to mixing_elbow.msh.h5 (default: $SIM_DATASETS/mixing_elbow.msh.h5)")
