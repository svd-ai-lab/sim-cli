"""Lazy + silent Warp initialization.

Warp prints a multi-line banner on first real use (e.g., `wp.get_devices()`),
which would corrupt our JSON stdout envelope. Capture and suppress; re-emit
on stderr for diagnostics.
"""
from __future__ import annotations

import contextlib
import io
import sys


@contextlib.contextmanager
def _redirect_stdout_to_buffer():
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = old


_initialized = False
_init_banner = ""


def init_warp_silently() -> None:
    """Force warp.init() while capturing its stdout banner."""
    global _initialized, _init_banner
    if _initialized:
        return
    import warp as wp  # noqa: PLC0415

    with _redirect_stdout_to_buffer() as buf:
        wp.get_devices()
    _init_banner = buf.getvalue()
    _initialized = True


def get_init_banner() -> str:
    return _init_banner
