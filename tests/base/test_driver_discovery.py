"""Tests for external driver discovery via entry_points.

Covers `sim.drivers._discover_external` in isolation: validation rules,
conflict policy with built-ins, deterministic ordering, and graceful
degradation when the entry-point machinery itself fails.

These tests do NOT install fake distributions — they monkey-patch the
`entry_points` symbol imported into `sim.drivers`. Real-distribution
end-to-end coverage belongs to the plugin packages themselves.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sim import drivers as drivers_mod


class _FakeEP:
    """Minimal stand-in for importlib.metadata.EntryPoint."""
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value


def _patch_eps(eps: list[_FakeEP]):
    """Patch the entry_points symbol in sim.drivers to yield `eps`."""
    return patch.object(
        drivers_mod, "entry_points",
        lambda group: eps if group == drivers_mod._ENTRY_POINT_GROUP else [],
    )


class TestSpecValidation(unittest.TestCase):
    def test_accepts_well_formed(self):
        self.assertTrue(drivers_mod._is_valid_spec("pkg.mod:Cls"))
        self.assertTrue(drivers_mod._is_valid_spec("a:B"))
        self.assertTrue(drivers_mod._is_valid_spec("a.b.c.d:E"))

    def test_rejects_malformed(self):
        for bad in [
            "",
            "no_colon",
            ":NoModule",
            "no_class:",
            "pkg.mod:Cls.extra",   # multi-segment class name not allowed
            "pkg-with-dash:Cls",   # not a valid identifier segment
            "pkg.mod:Cls Extra",   # space in class name
            "1pkg:Cls",            # leading digit in module
            None,                  # type: ignore[arg-type]
            123,                   # type: ignore[arg-type]
        ]:
            with self.subTest(spec=bad):
                self.assertFalse(drivers_mod._is_valid_spec(bad))


class TestDiscoverExternal(unittest.TestCase):
    def test_no_entry_points_returns_empty(self):
        with _patch_eps([]):
            self.assertEqual(drivers_mod._discover_external(), [])

    def test_valid_external_passes_through(self):
        eps = [_FakeEP("zzz_custom", "my_pkg.mod:MyDriver")]
        with _patch_eps(eps):
            result = drivers_mod._discover_external()
        self.assertEqual(result, [("zzz_custom", "my_pkg.mod:MyDriver")])

    def test_externals_sorted_by_name(self):
        eps = [
            _FakeEP("zeta", "p:Z"),
            _FakeEP("alpha", "p:A"),
            _FakeEP("mu", "p:M"),
        ]
        with _patch_eps(eps):
            result = drivers_mod._discover_external()
        self.assertEqual([n for n, _ in result], ["alpha", "mu", "zeta"])

    def test_conflict_with_builtin_skipped(self):
        # Pick a name guaranteed to be in _BUILTIN_REGISTRY.
        builtin_name = drivers_mod._BUILTIN_REGISTRY[0][0]
        eps = [_FakeEP(builtin_name, "evil_pkg:Hijacker")]
        with self.assertLogs("sim.drivers", level="WARNING") as logs:
            with _patch_eps(eps):
                result = drivers_mod._discover_external()
        self.assertEqual(result, [])
        self.assertTrue(any("shadows a built-in" in m for m in logs.output))

    def test_duplicate_external_names_first_wins(self):
        eps = [
            _FakeEP("dup", "first:A"),
            _FakeEP("dup", "second:B"),
        ]
        with self.assertLogs("sim.drivers", level="WARNING") as logs:
            with _patch_eps(eps):
                result = drivers_mod._discover_external()
        self.assertEqual(result, [("dup", "first:A")])
        self.assertTrue(any("duplicate external driver" in m for m in logs.output))

    def test_malformed_spec_skipped(self):
        eps = [
            _FakeEP("good", "ok.mod:Good"),
            _FakeEP("bad", "this is not a spec"),
        ]
        with self.assertLogs("sim.drivers", level="WARNING") as logs:
            with _patch_eps(eps):
                result = drivers_mod._discover_external()
        self.assertEqual(result, [("good", "ok.mod:Good")])
        self.assertTrue(any("malformed entry-point value" in m for m in logs.output))

    def test_entry_points_failure_returns_empty(self):
        def boom(group):
            raise RuntimeError("metadata corrupted")
        with self.assertLogs("sim.drivers", level="WARNING") as logs:
            with patch.object(drivers_mod, "entry_points", boom):
                result = drivers_mod._discover_external()
        self.assertEqual(result, [])
        self.assertTrue(any("lookup failed" in m for m in logs.output))


class TestRegistryComposition(unittest.TestCase):
    """Sanity checks on the actually-loaded _REGISTRY."""

    def test_contains_all_builtins(self):
        registry_names = [n for n, _ in drivers_mod._REGISTRY]
        for name, _ in drivers_mod._BUILTIN_REGISTRY:
            self.assertIn(name, registry_names)

    def test_builtins_appear_first(self):
        builtin_count = len(drivers_mod._BUILTIN_REGISTRY)
        prefix = drivers_mod._REGISTRY[:builtin_count]
        self.assertEqual(prefix, drivers_mod._BUILTIN_REGISTRY)


if __name__ == "__main__":
    unittest.main()
