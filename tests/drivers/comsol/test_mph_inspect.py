"""Unit tests for `sim.drivers.comsol.lib.mph_inspect`.

The fixtures are built in-memory with `zipfile.ZipFile`, mirroring the
exact entry layout of real MPH files probed against COMSOL 6.4 on a
Windows test host:

  * ``compact``: thermoelectric_lib.mph shape — modelinfo + dmodel +
    smodel + geommanager.
  * ``solved``: hydrogen_atom.mph shape — adds mesh, solution* blocks,
    savepoint, modelimage thumbnails.
  * ``preview``: lorenz_attractor.mph shape — only modelinfo +
    fileversion + index.txt + a 0-byte ``preview`` marker.
  * ``with_params``: synthetic `dmodel.xml` slice with three Global
    Parameters (the real Application Library samples we probed had
    none).

Real-host integration runs against `tests/inspect/probe_mph_inspect.py`
when COMSOL is available — gated like `probe_describe_physics.py`.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from sim.drivers.comsol.lib.mph_inspect import (
    MphArchive,
    MphEntry,
    _classify,
    _extract_parameters,
    _harvest_tags_from_smodel,
    _parse_fileversion,
    _parse_modelinfo,
    format_summary,
    inspect_mph,
    mph_diff,
)


# ----------------------------------------------------------------------
# Fixture builders
# ----------------------------------------------------------------------


def _modelinfo_xml(
    *,
    title: str = "Test Model",
    description: str = "Built in-memory by tests.",
    node_type: str = "compact",
    is_runnable: str = "off",
    last_computation_time: str = "",
    physics: str = "",
    geom_dim: str = "3",
    comsol_version: str = "6.4.0.272",
) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<modelInfo comsolVersion="{comsol_version}" '
        f'modelType="MODEL" nodeType="{node_type}" '
        f'isRunnable="{is_runnable}" '
        f'title="{title}" description="{description}" '
        f'lastComputationTime="{last_computation_time}" '
        'mainPartSDim="None">'
        '<historyInfo createdIn="COMSOL Multiphysics 6.4 (Build: 272)" '
        'author="COMSOL" createdDate="0" lastModifiedBy="" lastModifiedDate="0"/>'
        '<licenseInfo products=""/>'
        f'<physicsInfo physics="{physics}"/>'
        '<geometryInfo>'
        f'<geom tag="geom1" dimension="{geom_dim}"/>'
        '</geometryInfo>'
        '</modelInfo>'
    )


_DMODEL_PARAMS = """<?xml version="1.0" encoding="UTF-8"?>
<Model tag="Model1">
  <ModelParam tag="param" name="Parameters" created="0">
    <ModelParamGroupList tag="group">
      <ModelParamGroup tag="default" name="Parameters 1">
        <param T="33" param="L" value="1[m]" reference="length"/>
        <param T="33" param="W" value="0.5[m]" reference="width"/>
        <param T="33" param="T0" value="293.15[K]"/>
      </ModelParamGroup>
    </ModelParamGroupList>
  </ModelParam>
</Model>
"""


_DMODEL_NO_PARAMS = """<?xml version="1.0" encoding="UTF-8"?>
<Model tag="Model1">
  <ModelParam tag="param" name="Parameters" created="0">
    <ModelParamGroupList tag="group">
      <ModelParamGroup tag="default" name="Parameters 1">
      </ModelParamGroup>
    </ModelParamGroupList>
  </ModelParam>
</Model>
"""


_SMODEL_TAGGED = json.dumps({
    "apiClass": "Model",
    "tag": "Model",
    "nodes": [
        {
            "apiClass": "Physics",
            "tag": "ht",
            "type": "HeatTransfer",
            "nodes": [],
        },
        {
            "apiClass": "Study",
            "tag": "std1",
            "nodes": [
                {"apiClass": "Solution", "tag": "sol1"},
            ],
        },
        {
            "apiClass": "MaterialList",
            "nodes": [
                {"apiClass": "Material", "tag": "mat1"},
                {"apiClass": "Material", "tag": "mat2"},
            ],
        },
    ],
})


def _build_mph(tmp_path: Path, name: str, entries: dict[str, str | bytes]) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry, content in entries.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(entry, data)
    return path


@pytest.fixture
def compact_mph(tmp_path: Path) -> Path:
    return _build_mph(tmp_path, "compact.mph", {
        "fileversion": "2092:COMSOL 6.4.0.272\n",
        "modelinfo.xml": _modelinfo_xml(
            title="Compact Sample",
            description="A compact-only test model.",
            node_type="compact",
            physics="HeatTransfer",
        ),
        "model.xml": '<?xml version="1.0"?><Model/>\n',
        "dmodel.xml": _DMODEL_PARAMS,
        "smodel.json": _SMODEL_TAGGED,
        "fileids.xml": '<?xml version="1.0"?><FileIDs/>\n',
        "clusterignore.xml": '<?xml version="1.0"?><ClusterIgnore/>\n',
        "guimodel.xml": '<?xml version="1.0"?><GuiModel/>\n',
        "usedlicenses.txt": "COMSOL\n",
        "geommanager1.mphbin": b"\x00" * 168,
    })


@pytest.fixture
def solved_mph(tmp_path: Path) -> Path:
    return _build_mph(tmp_path, "solved.mph", {
        "fileversion": "2092:COMSOL 6.4.0.272\n",
        "modelinfo.xml": _modelinfo_xml(
            title="Solved Sample",
            description="With mesh + solutions.",
            node_type="solved",
            is_runnable="off",
            last_computation_time="3.678 s",
            physics="HeatTransfer",
        ),
        "model.xml": '<?xml version="1.0"?><Model/>\n',
        "dmodel.xml": _DMODEL_NO_PARAMS,
        "fileids.xml": '<?xml version="1.0"?><FileIDs/>\n',
        "clusterignore.xml": '<?xml version="1.0"?><ClusterIgnore/>\n',
        "guimodel.xml": '<?xml version="1.0"?><GuiModel/>\n',
        "usedlicenses.txt": "COMSOL\n",
        "geommanager1.mphbin": b"\x00" * 100,
        "geometry1.mphbin": b"\x00" * 2000,
        "mesh1.mphbin": b"\x00" * 50_000,
        "xmesh1.mphbin": b"\x00" * 400_000,
        "solution1.mphbin": b"\x00" * 1000,
        "solutionblock1.mphbin": b"\x00" * 30_000,
        "solutionblock2.mphbin": b"\x00" * 280_000,
        "solutionstatic1.mphbin": b"\x00" * 16_000,
        "savepoint1/savepoint.xml": '<?xml version="1.0"?><Savepoint/>\n',
        "savepoint1/model.zip": b"\x00" * 15_000,
        "modelimage.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 4500,
        "modelimage_large.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 13_000,
    })


@pytest.fixture
def preview_mph(tmp_path: Path) -> Path:
    return _build_mph(tmp_path, "preview.mph", {
        "fileversion": "2092:COMSOL 6.4.0.272\n",
        "modelinfo.xml": _modelinfo_xml(
            title="Lorenz Attractor",
            description="Library placeholder.",
            node_type="preview",
        ),
        "model.xml": '<?xml version="1.0"?><Model/>\n',
        "modelimage.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 45_000,
        "index.txt": "preview metadata\n",
        "preview": b"",
    })


# ----------------------------------------------------------------------
# Pure-helper unit tests
# ----------------------------------------------------------------------


def test_classify_solution_buckets():
    assert _classify("solution1.mphbin") == "solution"
    assert _classify("solutionblock1.mphbin") == "solution"
    assert _classify("solutionstatic1.mphbin") == "solution"


def test_classify_mesh_and_geometry():
    assert _classify("mesh1.mphbin") == "mesh"
    assert _classify("xmesh1.mphbin") == "mesh"
    assert _classify("geometry1.mphbin") == "geometry"
    assert _classify("geometry42.mphbin") == "geometry"
    assert _classify("geommanager1.mphbin") == "geometry"


def test_classify_savepoint_and_image():
    assert _classify("savepoint1/savepoint.xml") == "savepoint"
    assert _classify("savepoint12/model.zip") == "savepoint"
    assert _classify("modelimage.png") == "image"
    assert _classify("modelimage_large.png") == "image"


def test_classify_data_and_binary_and_other():
    assert _classify("modelinfo.xml") == "data"
    assert _classify("smodel.json") == "data"
    assert _classify("usedlicenses.txt") == "data"
    assert _classify("fileversion") == "data"
    assert _classify("custom.mphbin") == "binary"
    assert _classify("preview") == "other"


def test_parse_fileversion_happy_path():
    sv, vs = _parse_fileversion("2092:COMSOL 6.4.0.272\n")
    assert sv == 2092
    assert vs == "6.4.0.272"


def test_parse_fileversion_empty_or_malformed():
    assert _parse_fileversion("") == (None, "")
    sv, vs = _parse_fileversion("garbage")
    assert sv is None
    assert vs == "garbage"


def test_parse_modelinfo_round_trip():
    info = _parse_modelinfo(_modelinfo_xml(
        title="X", description="Y", node_type="solved",
        is_runnable="on", last_computation_time="42.0 s",
        physics="HeatTransfer", geom_dim="2",
    ))
    assert info.title == "X"
    assert info.description == "Y"
    assert info.node_type == "solved"
    assert info.is_runnable is True
    assert info.last_computation_time == "42.0 s"
    assert info.physics == "HeatTransfer"
    assert info.geometries == [{"tag": "geom1", "dimension": "2"}]
    assert info.created_in.startswith("COMSOL Multiphysics")


def test_parse_modelinfo_falls_back_to_modelTitle():
    """Application Library models put title under modelTitle, not title."""
    xml = (
        '<?xml version="1.0"?>'
        '<modelInfo comsolVersion="6.4.0.272" modelType="MODEL" '
        'nodeType="compact" isRunnable="off" '
        'modelTitle="Library Sample" modelDescription="Library desc">'
        '<historyInfo createdIn="x" author="y" lastModifiedBy="z"/>'
        '<licenseInfo products=""/>'
        '<physicsInfo physics=""/>'
        '<geometryInfo/>'
        '</modelInfo>'
    )
    info = _parse_modelinfo(xml)
    assert info.title == "Library Sample"
    assert info.description == "Library desc"


def test_parse_modelinfo_size_fields_for_preview():
    xml = (
        '<?xml version="1.0"?>'
        '<modelInfo comsolVersion="6.4.0.272" modelType="MODEL" '
        'nodeType="preview" isRunnable="off" '
        'title="Preview" description="x" '
        'solvedFileSize="4843001" compactFileSize="2104217">'
        '<historyInfo author="y"/>'
        '<licenseInfo products=""/>'
        '<physicsInfo physics=""/>'
        '<geometryInfo/>'
        '</modelInfo>'
    )
    info = _parse_modelinfo(xml)
    assert info.solved_file_size == 4843001
    assert info.compact_file_size == 2104217


def test_extract_parameters_from_real_dmodel_slice():
    params = _extract_parameters(_DMODEL_PARAMS)
    assert set(params) == {"L", "W", "T0"}
    assert params["L"] == {"value": "1[m]", "reference": "length"}
    assert params["W"] == {"value": "0.5[m]", "reference": "width"}
    assert params["T0"] == {"value": "293.15[K]", "reference": ""}


def test_extract_parameters_no_params_returns_empty_dict():
    assert _extract_parameters(_DMODEL_NO_PARAMS) == {}


def test_extract_parameters_ignores_material_level_t33_entries():
    """T=33 also appears under MaterialModel — those are NOT global
    parameters and must not be surfaced."""
    xml = """<?xml version="1.0"?>
<Model tag="Model1">
  <ModelParam tag="param" name="Parameters" created="0">
    <ModelParamGroupList tag="group">
      <ModelParamGroup tag="default" name="Parameters 1">
        <param T="33" param="L" value="1[m]" reference="length"/>
      </ModelParamGroup>
    </ModelParamGroupList>
  </ModelParam>
  <Material tag="mat1">
    <MaterialModel tag="def">
      <param T="33" param="density" value="1|1,'7700'" reference=""/>
      <param T="33" param="heatcapacity" value="1|1,'154'" reference=""/>
    </MaterialModel>
  </Material>
</Model>
"""
    params = _extract_parameters(xml)
    assert set(params) == {"L"}


def test_harvest_tags_from_smodel_collects_all_matches():
    s = json.loads(_SMODEL_TAGGED)
    assert _harvest_tags_from_smodel(s, "Physics") == ["ht"]
    assert _harvest_tags_from_smodel(s, "Material") == ["mat1", "mat2"] or \
        _harvest_tags_from_smodel(s, "Material") == ["mat2", "mat1"]
    assert _harvest_tags_from_smodel(s, "Solution") == ["sol1"]
    assert _harvest_tags_from_smodel(s, "Study") == ["std1"]


# ----------------------------------------------------------------------
# MphArchive end-to-end tests
# ----------------------------------------------------------------------


def test_archive_rejects_non_zip(tmp_path: Path):
    bad = tmp_path / "not_a_mph.mph"
    bad.write_bytes(b"\x00\x01\x02\x03 not a zip")
    with pytest.raises(ValueError, match="not a ZIP"):
        MphArchive(bad)


def test_archive_rejects_missing_path(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        MphArchive(tmp_path / "nope.mph")


def test_compact_mph_summary(compact_mph: Path):
    s = inspect_mph(compact_mph)
    assert s["title"] == "Compact Sample"
    assert s["node_type"] == "compact"
    assert s["schema_version"] == 2092
    assert s["saved_in_version"] == "6.4.0.272"
    assert s["physics_info"] == "HeatTransfer"
    assert s["used_licenses"] == ["COMSOL"]
    assert "L" in s["parameters"]
    assert s["parameters"]["L"]["value"] == "1[m]"
    assert s["parameters"]["L"]["reference"] == "length"
    assert s["physics_tags"] == ["ht"]
    assert s["study_tags"] == ["std1"]
    assert s["solution_tags"] == ["sol1"]
    assert "solution" not in s["size_breakdown"]


def test_solved_mph_size_breakdown(solved_mph: Path):
    s = inspect_mph(solved_mph)
    assert s["node_type"] == "solved"
    assert s["last_computation_time"] == "3.678 s"
    sizes = s["size_breakdown"]
    assert sizes["solution"] == 1000 + 30_000 + 280_000 + 16_000
    assert sizes["mesh"] == 50_000 + 400_000
    assert sizes["geometry"] == 100 + 2000
    assert sizes["image"] > 0
    assert sizes["savepoint"] > 0


def test_solved_mph_has_no_parameters_when_dmodel_block_empty(solved_mph: Path):
    s = inspect_mph(solved_mph)
    assert s["parameters"] == {}


def test_preview_mph(preview_mph: Path):
    s = inspect_mph(preview_mph)
    assert s["node_type"] == "preview"
    assert s["title"] == "Lorenz Attractor"
    assert s["parameters"] == {}
    assert s["physics_tags"] == []
    assert "image" in s["size_breakdown"]


def test_archive_property_predicates(compact_mph: Path, solved_mph: Path, preview_mph: Path):
    with MphArchive(compact_mph) as m:
        assert m.is_compact is True
        assert m.is_solved is False
        assert m.is_preview is False
    with MphArchive(solved_mph) as m:
        assert m.is_solved is True
        assert m.is_compact is False
    with MphArchive(preview_mph) as m:
        assert m.is_preview is True
        assert m.is_solved is False


def test_archive_entries_classify_correctly(solved_mph: Path):
    with MphArchive(solved_mph) as m:
        entries = m.entries()
    by_bucket: dict[str, list[str]] = {}
    for e in entries:
        by_bucket.setdefault(e.bucket, []).append(e.name)
    assert "solution1.mphbin" in by_bucket["solution"]
    assert "mesh1.mphbin" in by_bucket["mesh"]
    assert "geommanager1.mphbin" in by_bucket["geometry"]
    assert "modelimage.png" in by_bucket["image"]
    assert any(n.startswith("savepoint1/") for n in by_bucket["savepoint"])
    assert "modelinfo.xml" in by_bucket["data"]


def test_archive_close_idempotent(compact_mph: Path):
    m = MphArchive(compact_mph)
    m.close()
    m.close()  # second close must not raise


def test_archive_caches_modelinfo(compact_mph: Path):
    with MphArchive(compact_mph) as m:
        info1 = m.model_info()
        info2 = m.model_info()
        assert info1 is info2


# ----------------------------------------------------------------------
# Diff
# ----------------------------------------------------------------------


def test_mph_diff_reports_no_changes_for_identical_files(tmp_path: Path, compact_mph: Path):
    same = _build_mph(tmp_path, "same.mph", {
        "fileversion": "2092:COMSOL 6.4.0.272\n",
        "modelinfo.xml": _modelinfo_xml(
            title="Compact Sample",
            description="A compact-only test model.",
            node_type="compact",
            physics="HeatTransfer",
        ),
        "model.xml": '<?xml version="1.0"?><Model/>\n',
        "dmodel.xml": _DMODEL_PARAMS,
        "smodel.json": _SMODEL_TAGGED,
        "fileids.xml": '<?xml version="1.0"?><FileIDs/>\n',
        "clusterignore.xml": '<?xml version="1.0"?><ClusterIgnore/>\n',
        "guimodel.xml": '<?xml version="1.0"?><GuiModel/>\n',
        "usedlicenses.txt": "COMSOL\n",
        "geommanager1.mphbin": b"\x00" * 168,
    })
    d = mph_diff(compact_mph, same)
    # Both files have the same logical content but different file_size on disk
    # because deflate is not deterministic across filenames; ignore file_size
    # if present and keep the rest.
    d["scalar_changes"].pop("file_size", None)
    assert d["scalar_changes"] == {}
    assert d["parameters"]["added"] == []
    assert d["parameters"]["removed"] == []
    assert d["parameters"]["changed"] == {}
    assert d["entries"]["added"] == []
    assert d["entries"]["removed"] == []
    assert d["tags"] == {}


def test_mph_diff_detects_param_changes(tmp_path: Path, compact_mph: Path):
    """Same archive shape, different parameter values → reported under
    `parameters.changed`."""
    other_dmodel = _DMODEL_PARAMS.replace(
        '<param T="33" param="L" value="1[m]" reference="length"/>',
        '<param T="33" param="L" value="2[m]" reference="length"/>',
    ).replace(
        '<param T="33" param="W" value="0.5[m]" reference="width"/>',
        '<param T="33" param="NEW_PARAM" value="42" reference=""/>',
    )
    other = _build_mph(tmp_path, "other.mph", {
        "fileversion": "2092:COMSOL 6.4.0.272\n",
        "modelinfo.xml": _modelinfo_xml(
            title="Compact Sample",
            description="A compact-only test model.",
            node_type="compact",
            physics="HeatTransfer",
        ),
        "model.xml": '<?xml version="1.0"?><Model/>\n',
        "dmodel.xml": other_dmodel,
        "smodel.json": _SMODEL_TAGGED,
        "fileids.xml": '<?xml version="1.0"?><FileIDs/>\n',
        "clusterignore.xml": '<?xml version="1.0"?><ClusterIgnore/>\n',
        "guimodel.xml": '<?xml version="1.0"?><GuiModel/>\n',
        "usedlicenses.txt": "COMSOL\n",
        "geommanager1.mphbin": b"\x00" * 168,
    })
    d = mph_diff(compact_mph, other)
    assert "L" in d["parameters"]["changed"]
    assert d["parameters"]["changed"]["L"]["a"]["value"] == "1[m]"
    assert d["parameters"]["changed"]["L"]["b"]["value"] == "2[m]"
    assert d["parameters"]["added"] == ["NEW_PARAM"]
    assert d["parameters"]["removed"] == ["W"]


def test_mph_diff_detects_solved_vs_compact(compact_mph: Path, solved_mph: Path):
    d = mph_diff(compact_mph, solved_mph)
    assert d["scalar_changes"]["node_type"] == {"a": "compact", "b": "solved"}
    assert any(e.startswith("solution") for e in d["entries"]["added"])
    assert any(e.startswith("mesh") for e in d["entries"]["added"])


# ----------------------------------------------------------------------
# format_summary
# ----------------------------------------------------------------------


def test_format_summary_includes_title_and_node_type(compact_mph: Path):
    text = format_summary(inspect_mph(compact_mph))
    assert "Compact Sample" in text
    assert "compact" in text
    assert "HeatTransfer" not in text or "physics" not in text  # physics is tags here
    # Parameters block
    assert "L = 1[m]" in text
    assert "T0 = 293.15[K]" in text


def test_format_summary_compact_for_preview(preview_mph: Path):
    text = format_summary(inspect_mph(preview_mph))
    assert "preview" in text
    assert "Lorenz Attractor" in text


def test_format_summary_truncates_long_descriptions(tmp_path: Path):
    long_desc = "A " * 200
    long_path = _build_mph(tmp_path, "long.mph", {
        "fileversion": "2092:COMSOL 6.4.0.272\n",
        "modelinfo.xml": _modelinfo_xml(description=long_desc),
        "model.xml": '<?xml version="1.0"?><Model/>\n',
        "dmodel.xml": _DMODEL_NO_PARAMS,
    })
    text = format_summary(inspect_mph(long_path))
    desc_lines = [ln for ln in text.splitlines() if "description:" in ln]
    assert desc_lines, "expected a description line"
    assert len(desc_lines[0]) < 120


# ----------------------------------------------------------------------
# Real-MPH integration (gated)
# ----------------------------------------------------------------------


def _real_mph_paths() -> list[Path]:
    """Look for real `.mph` fixtures via env. Skipped if unset."""
    import os
    root = os.environ.get("COMSOL_MPH_FIXTURES")
    if not root:
        return []
    return sorted(Path(root).glob("*.mph"))


@pytest.mark.skipif(
    not _real_mph_paths(),
    reason="set COMSOL_MPH_FIXTURES to a directory with .mph files to enable",
)
def test_real_mph_summary_smoke():
    for p in _real_mph_paths():
        s = inspect_mph(p)
        assert s["path"] == str(p)
        assert s["node_type"] in {"compact", "solved", "preview", ""}
        assert s["schema_version"] is None or isinstance(s["schema_version"], int)
        assert isinstance(s["size_breakdown"], dict)


# ----------------------------------------------------------------------
# MphFileProbe
# ----------------------------------------------------------------------


class _StubCtx:
    """Duck-typed stand-in for InspectCtx — enough to drive MphFileProbe."""

    def __init__(self, workdir, workdir_before=None):
        self.workdir = str(workdir)
        self.workdir_before = workdir_before


def test_probe_emits_summary_for_new_mph(tmp_path: Path, compact_mph: Path):
    from sim.drivers.comsol.lib import MphFileProbe

    workdir = tmp_path / "wd"
    workdir.mkdir()
    target = workdir / "out.mph"
    target.write_bytes(compact_mph.read_bytes())

    probe = MphFileProbe(only_new=True)
    ctx = _StubCtx(workdir, workdir_before=[])
    assert probe.applies(ctx)
    result = probe.probe(ctx)
    assert any(d.code == "comsol.mph.summary" for d in result.diagnostics)
    diag = next(d for d in result.diagnostics if d.code == "comsol.mph.summary")
    assert diag.severity == "info"
    assert "Compact Sample" in diag.message
    assert diag.extra["node_type"] == "compact"
    assert diag.extra["parameter_count"] == 3


def test_probe_skips_files_present_in_baseline(tmp_path: Path, compact_mph: Path):
    from sim.drivers.comsol.lib import MphFileProbe

    workdir = tmp_path / "wd"
    workdir.mkdir()
    pre = workdir / "preexisting.mph"
    pre.write_bytes(compact_mph.read_bytes())
    new = workdir / "new.mph"
    new.write_bytes(compact_mph.read_bytes())

    probe = MphFileProbe(only_new=True)
    ctx = _StubCtx(workdir, workdir_before=["preexisting.mph"])
    result = probe.probe(ctx)

    paths = [d.extra["path"] for d in result.diagnostics if d.extra.get("path")]
    assert any(p.endswith("new.mph") for p in paths)
    assert not any(p.endswith("preexisting.mph") for p in paths)


def test_probe_describes_all_when_only_new_is_false(tmp_path: Path, compact_mph: Path):
    from sim.drivers.comsol.lib import MphFileProbe

    workdir = tmp_path / "wd"
    workdir.mkdir()
    a = workdir / "a.mph"
    a.write_bytes(compact_mph.read_bytes())
    b = workdir / "b.mph"
    b.write_bytes(compact_mph.read_bytes())

    probe = MphFileProbe(only_new=False)
    ctx = _StubCtx(workdir, workdir_before=["a.mph"])  # baseline ignored
    result = probe.probe(ctx)

    paths = [d.extra["path"] for d in result.diagnostics if d.extra.get("path")]
    assert any(p.endswith("a.mph") for p in paths)
    assert any(p.endswith("b.mph") for p in paths)


def test_probe_emits_warning_on_corrupt_mph(tmp_path: Path):
    from sim.drivers.comsol.lib import MphFileProbe

    workdir = tmp_path / "wd"
    workdir.mkdir()
    bad = workdir / "broken.mph"
    bad.write_bytes(b"\x00" * 32)  # not a ZIP

    probe = MphFileProbe(only_new=False)
    ctx = _StubCtx(workdir)
    result = probe.probe(ctx)
    parse_failed = [d for d in result.diagnostics if d.code == "comsol.mph.parse_failed"]
    assert len(parse_failed) == 1
    assert parse_failed[0].severity == "warning"
    assert "broken.mph" in parse_failed[0].message


def test_probe_caps_at_max_files(tmp_path: Path, compact_mph: Path):
    from sim.drivers.comsol.lib import MphFileProbe

    workdir = tmp_path / "wd"
    workdir.mkdir()
    for i in range(7):
        f = workdir / f"sample_{i}.mph"
        f.write_bytes(compact_mph.read_bytes())

    probe = MphFileProbe(only_new=False, max_files=3)
    ctx = _StubCtx(workdir)
    result = probe.probe(ctx)
    summaries = [d for d in result.diagnostics if d.code == "comsol.mph.summary"]
    assert len(summaries) == 3


def test_probe_does_not_apply_when_workdir_missing():
    from sim.drivers.comsol.lib import MphFileProbe

    probe = MphFileProbe()
    ctx = _StubCtx("/no/such/dir/anywhere")
    assert probe.applies(ctx) is False


# Keep `io` imported — reserved for future stream-based helpers.
_ = io
