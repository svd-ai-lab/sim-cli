"""Recipe interpreter unit tests — shape/schema validation, no Warp import."""
from __future__ import annotations

import json

import pytest


HAS_WARP_NEWTON = False
try:
    import warp  # noqa: F401
    import newton  # noqa: F401
    HAS_WARP_NEWTON = True
except ImportError:
    pass


def _skip_if_missing():
    if not HAS_WARP_NEWTON:
        pytest.skip("warp + newton not installed in this interpreter")


class TestSchemaCheck:
    def test_accepts_new_schema(self):
        _skip_if_missing()
        from sim.drivers.newton.recipes import _execute_recipe_on_builder
        import newton

        builder = newton.ModelBuilder()
        _execute_recipe_on_builder(builder, {
            "schema": "sim/newton/recipe/v1",
            "ops": [{"op": "add_ground_plane", "args": {}}],
        })
        assert builder.shape_count >= 1

    def test_accepts_legacy_schema(self):
        _skip_if_missing()
        from sim.drivers.newton.recipes import _execute_recipe_on_builder
        import newton

        builder = newton.ModelBuilder()
        _execute_recipe_on_builder(builder, {
            "schema": "newton-cli/recipe/v1",
            "ops": [{"op": "add_ground_plane", "args": {}}],
        })
        assert builder.shape_count >= 1

    def test_rejects_wrong_schema(self):
        _skip_if_missing()
        from sim.drivers.newton.recipes import _execute_recipe_on_builder, RecipeError
        import newton

        builder = newton.ModelBuilder()
        with pytest.raises(RecipeError, match="schema"):
            _execute_recipe_on_builder(builder, {"schema": "bogus/v1", "ops": []})

    def test_rejects_non_list_ops(self):
        _skip_if_missing()
        from sim.drivers.newton.recipes import _execute_recipe_on_builder, RecipeError
        import newton

        builder = newton.ModelBuilder()
        with pytest.raises(RecipeError, match="ops"):
            _execute_recipe_on_builder(builder, {
                "schema": "sim/newton/recipe/v1",
                "ops": {"not": "a list"},
            })

    def test_rejects_unknown_method(self):
        _skip_if_missing()
        from sim.drivers.newton.recipes import _execute_recipe_on_builder, RecipeError
        import newton

        builder = newton.ModelBuilder()
        with pytest.raises(RecipeError, match="no method"):
            _execute_recipe_on_builder(builder, {
                "schema": "sim/newton/recipe/v1",
                "ops": [{"op": "add_unicorn", "args": {}}],
            })


class TestJsonParsing:
    def test_bad_json_raises(self, tmp_path):
        _skip_if_missing()
        from sim.drivers.newton.recipes import build_model_from_recipe
        p = tmp_path / "r.json"
        p.write_text("{not json")
        with pytest.raises(json.JSONDecodeError):
            build_model_from_recipe(p)
