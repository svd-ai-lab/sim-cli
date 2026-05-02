"""Tests for plugin catalogue/discovery helpers."""
from __future__ import annotations

from sim.plugin_catalog import list_catalog, normalize_catalog


def test_normalize_current_index_shape_defaults_to_package_spec():
    rows = normalize_catalog({
        "schema_version": 1,
        "plugins": [
            {
                "name": "ltspice",
                "summary": "LTspice driver",
                "homepage": "https://github.com/svd-ai-lab/sim-plugin-ltspice",
                "license_class": "oss",
                "latest_version": "0.2.3",
            }
        ],
    })
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "ltspice"
    assert row.package == "sim-plugin-ltspice"
    assert row.install_command == "sim plugin install sim-plugin-ltspice"
    assert row.latest_version == "0.2.3"


def test_normalize_future_dict_shape_and_install_command():
    rows = normalize_catalog({
        "plugins": {
            "mechanical": {
                "package": "sim-plugin-mechanical",
                "license_class": "commercial-wrapper",
                "install": {
                    "command": "sim plugin install sim-plugin-mechanical --extra-index-url https://example.com/simple/"
                },
            }
        }
    })
    assert rows[0].name == "mechanical"
    assert rows[0].license_class == "commercial-wrapper"
    assert "--extra-index-url" in rows[0].install_command


def test_list_catalog_search_uses_catalog_without_install_resolution(monkeypatch):
    from sim import plugin_catalog

    def fake_fetch_catalog(**kwargs):
        return {
            "plugins": [
                {"name": "ltspice", "summary": "Circuit simulation"},
                {"name": "flotherm", "summary": "Thermal simulation"},
            ]
        }

    monkeypatch.setattr(plugin_catalog, "fetch_catalog", fake_fetch_catalog)
    rows = list_catalog(query="thermal")
    assert [row.name for row in rows] == ["flotherm"]
    assert rows[0].install_command == "sim plugin install sim-plugin-flotherm"
