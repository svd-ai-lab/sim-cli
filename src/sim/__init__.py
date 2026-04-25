"""sim — unified CLI for LLM agents to control CAD/CAE simulation software."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sim-runtime")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
