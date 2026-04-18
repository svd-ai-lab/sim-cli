"""Introspect module unit tests — requires newton to be importable."""
from __future__ import annotations

import pytest


HAS_NEWTON = False
try:
    import newton  # noqa: F401
    HAS_NEWTON = True
except ImportError:
    pass


@pytest.fixture(autouse=True)
def _skip_if_missing():
    if not HAS_NEWTON:
        pytest.skip("newton not installed in this interpreter")


class TestPrivateGuard:
    def test_private_module_name_rejected(self):
        from sim.drivers.newton.introspect import assert_public, PrivateModuleError

        with pytest.raises(PrivateModuleError):
            assert_public("newton._src.internal")

    def test_private_in_describe(self):
        from sim.drivers.newton.introspect import describe_symbol, PrivateModuleError

        with pytest.raises(PrivateModuleError):
            describe_symbol("newton._src.foo")


class TestListSymbols:
    def test_top_level_newton_has_symbols(self):
        from sim.drivers.newton.introspect import list_symbols

        syms = list_symbols("newton")
        names = {s.name for s in syms}
        assert "ModelBuilder" in names

    def test_unknown_module_rejected(self):
        from sim.drivers.newton.introspect import list_symbols, PrivateModuleError

        with pytest.raises(PrivateModuleError):
            list_symbols("random.module")

    def test_full_walk_nonempty(self):
        from sim.drivers.newton.introspect import list_symbols

        syms = list_symbols()
        assert len(syms) > 5


class TestDescribeSymbol:
    def test_describe_model_builder(self):
        from sim.drivers.newton.introspect import describe_symbol

        info = describe_symbol("ModelBuilder")
        assert info["name"] == "ModelBuilder"
        assert info["kind"] == "class"
        assert isinstance(info["doc"], str)

    def test_describe_unknown_raises(self):
        from sim.drivers.newton.introspect import describe_symbol

        with pytest.raises(LookupError):
            describe_symbol("DefinitelyNotASymbolZZZ")
