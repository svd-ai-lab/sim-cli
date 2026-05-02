"""Tests for plugin catalogue/discovery helpers."""
from __future__ import annotations

from sim.plugin_catalog import list_catalog, normalize_catalog


def test_normalize_v2_pypi_entry():
    rows = normalize_catalog({
        "schema_version": 2,
        "plugins": [
            {
                "id": "ltspice",
                "name": "LTspice",
                "distribution": "pypi",
                "install": "sim-plugin-ltspice==0.2.3",
                "version": "0.2.3",
                "summary": "LTspice driver",
                "homepage": "https://github.com/svd-ai-lab/sim-plugin-ltspice",
                "license_class": "oss",
            }
        ],
    })
    assert len(rows) == 1
    row = rows[0]
    assert row.id == "ltspice"
    assert row.name == "LTspice"
    assert row.distribution == "pypi"
    assert row.install == "sim-plugin-ltspice==0.2.3"
    assert row.version == "0.2.3"


def test_normalize_v2_wheel_entry_carries_install_url_with_hash():
    rows = normalize_catalog({
        "schema_version": 2,
        "plugins": [
            {
                "id": "fluent",
                "name": "Ansys Fluent",
                "distribution": "wheel",
                "install": "https://cdn.svdailab.com/wheels/sim_plugin_fluent-0.1.4-py3-none-any.whl#sha256=abcd",
                "version": "0.1.4",
                "license_class": "commercial",
            }
        ],
    })
    assert rows[0].id == "fluent"
    assert rows[0].distribution == "wheel"
    assert rows[0].install.startswith("https://cdn.svdailab.com/")
    assert "#sha256=" in rows[0].install
    assert rows[0].license_class == "commercial"


def test_normalize_legacy_v1_entry_synthesizes_install_string():
    """Old-shape entries (no ``install``, just ``package``/``latest_version``)
    still produce a usable install string so the catalogue can migrate
    independently of sim-cli releases."""
    rows = normalize_catalog({
        "schema_version": 1,
        "plugins": [
            {
                "name": "ltspice",
                "summary": "LTspice driver",
                "homepage": "https://github.com/svd-ai-lab/sim-plugin-ltspice",
                "license_class": "oss",
                "package": "sim-plugin-ltspice",
                "latest_version": "0.2.3",
            }
        ],
    })
    assert len(rows) == 1
    row = rows[0]
    assert row.id == "ltspice"
    # Legacy fallback synthesizes the install string from package + version.
    assert row.install == "sim-plugin-ltspice==0.2.3"
    assert row.version == "0.2.3"
    assert row.distribution == "pypi"


def test_normalize_legacy_v1_wheel_url_entry():
    rows = normalize_catalog({
        "plugins": [
            {
                "name": "fluent",
                "license_class": "commercial",
                "latest_version": "0.1.4",
                "latest_wheel_url": "https://cdn.svdailab.com/wheels/sim_plugin_fluent-0.1.4-py3-none-any.whl",
            }
        ],
    })
    row = rows[0]
    assert row.install == "https://cdn.svdailab.com/wheels/sim_plugin_fluent-0.1.4-py3-none-any.whl"
    assert row.distribution == "wheel"


def test_normalize_dict_shape_promotes_key_to_id():
    rows = normalize_catalog({
        "plugins": {
            "ltspice": {
                "name": "LTspice",
                "distribution": "pypi",
                "install": "sim-plugin-ltspice==0.2.3",
                "version": "0.2.3",
            }
        }
    })
    assert rows[0].id == "ltspice"
    assert rows[0].name == "LTspice"


def test_list_catalog_query_filters_without_install_resolution(monkeypatch):
    from sim import plugin_catalog

    def fake_fetch_catalog(**kwargs):
        return {
            "schema_version": 2,
            "plugins": [
                {
                    "id": "ltspice",
                    "name": "LTspice",
                    "distribution": "pypi",
                    "install": "sim-plugin-ltspice==0.2.3",
                    "summary": "Circuit simulation",
                },
                {
                    "id": "flotherm",
                    "name": "Flotherm",
                    "distribution": "wheel",
                    "install": "https://cdn.svdailab.com/wheels/sim_plugin_flotherm-0.1.1-py3-none-any.whl",
                    "summary": "Thermal simulation",
                },
            ]
        }

    monkeypatch.setattr(plugin_catalog, "fetch_catalog", fake_fetch_catalog)
    rows = list_catalog(query="thermal")
    assert [row.id for row in rows] == ["flotherm"]
    assert rows[0].install.startswith("https://")
