from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tools" / "audit_python_floor.py"


spec = importlib.util.spec_from_file_location("audit_python_floor", TOOL_PATH)
assert spec is not None and spec.loader is not None
audit_python_floor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit_python_floor
spec.loader.exec_module(audit_python_floor)


def test_audit_repo_reports_declared_floors_and_workflows(tmp_path: Path) -> None:
    repo = tmp_path / "sim-plugin-example"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "pyproject.toml").write_text(
        """
[project]
name = "sim-plugin-example"
requires-python = ">=3.10"
classifiers = [
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.12",
]
""".strip(),
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text(
        'version = 1\nrequires-python = ">=3.10"\n',
        encoding="utf-8",
    )
    (repo / ".github" / "workflows" / "ci.yml").write_text(
        """
jobs:
  test:
    strategy:
      matrix:
        python: ["3.10", "3.12"]
    steps:
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: ${{ matrix.python }}
""".strip(),
        encoding="utf-8",
    )
    (repo / "src" / "driver.py").write_text("print('ok')\n", encoding="utf-8")

    audit = audit_python_floor.audit_repo(repo)

    assert audit.name == "sim-plugin-example"
    assert audit.requires_python == ">=3.10"
    assert audit.lock_requires_python == ">=3.10"
    assert "Programming Language :: Python :: 3.10" in audit.python_classifiers
    assert {item.value for item in audit.workflow_python_versions} == {
        "3.10",
        "3.12",
        "${{ matrix.python }}",
    }
    assert audit.python39_blockers == []


def test_audit_repo_flags_common_python39_blockers(tmp_path: Path) -> None:
    repo = tmp_path / "sim-cli"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        """
[project]
name = "sim-cli-core"
requires-python = ">=3.10"
""".strip(),
        encoding="utf-8",
    )
    (repo / "src" / "syntax.py").write_text(
        """
from dataclasses import dataclass
import tomllib

@dataclass(slots=True)
class Thing:
    value: int | None

def classify(value):
    match value:
        case 1:
            return "one"
""".lstrip(),
        encoding="utf-8",
    )

    audit = audit_python_floor.audit_repo(repo)

    kinds = {item.kind for item in audit.python39_blockers}
    assert "tomllib-without-fallback" in kinds
    assert "dataclass-slots" in kinds
    assert "pep604-runtime-union" in kinds
    assert "match-statement" in kinds
    assert "match-case" in kinds


def test_render_text_includes_interpreter_check() -> None:
    report = {
        "repos": [
            {
                "name": "sim-cli-core",
                "path": "repo",
                "requires_python": ">=3.10",
                "lock_requires_python": ">=3.10",
                "python_classifiers": [],
                "workflow_python_versions": [],
                "python39_blockers": [],
            }
        ],
        "interpreter_checks": {"3.9": False},
    }

    rendered = audit_python_floor.render_text(report)

    assert "Python floor audit" in rendered
    assert "Python 3.9: not found" in rendered
