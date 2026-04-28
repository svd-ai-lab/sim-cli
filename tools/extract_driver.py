"""Phase 1.5 codemod — lift one OSS driver out of sim-cli + sim-skills.

USAGE
-----

    python tools/extract_driver.py <driver-name> --output ../sim-plugin-<name>
    python tools/extract_driver.py <driver-name> --output ../sim-plugin-<name> --dry-run

The codemod turns the manual work that produced ``sim-plugin-coolprop``
in svd-ai-lab/sim-proj#72 into something repeatable. It produces an
on-disk plugin tree at ``--output`` and prints the three coordinated
diffs that need to land in sim-cli, sim-skills, and sim-plugin-index.

It deliberately does NOT:
  * call ``gh repo create`` (visibility is a human decision);
  * tag a release;
  * push to remotes;
  * open PRs.

Those steps stay human-gated per the autonomous playbook — the codemod
prepares the diffs; a human reviews them before they land.

CONTRACT
--------

For a driver ``<name>`` registered as ``("<name>", "sim.drivers.<name>:<Class>Driver")``:

1. ``src/sim/drivers/<name>/``                     -> plugin/src/sim_plugin_<name>/
2. ``tests/drivers/<name>/``                       -> plugin/tests/
3. ``tests/fixtures/<name>_*.py``                  -> plugin/fixtures/
4. ``tests/execution/<name>/``                     -> plugin/tests/
5. ``../sim-skills/<name>/``                       -> plugin/src/sim_plugin_<name>/_skills/<name>/
6. Plugin gets pyproject.toml, README.md, LICENSE, .gitignore, tests/__init__.py.
7. Plugin's __init__.py exports {Driver, skills_dir, plugin_info}.
8. Test file ``test_protocol.py`` is added (assert_protocol_conformance).
9. Test file ``test_wheel_contents.py`` is added (locks _skills/ shipping).

Sources of truth (do NOT hard-code paths inside this script unless tested):
  * Registry tuple                  -> sim/drivers/__init__.py
  * Plugin's compatibility.yaml     -> if present in sim/drivers/<name>/
  * License (Apache-2.0)            -> shared template
  * sim-runtime pin                 -> CLI flag (defaults to current main)

The reference dry-run target is ``coolprop``: running this codemod
against coolprop SHOULD produce a tree byte-for-byte identical (modulo
timestamps + committer metadata) to what landed in
svd-ai-lab/sim-plugin-coolprop@v0.1.0.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SIM_CLI = Path(__file__).resolve().parent.parent
SIM_SKILLS = SIM_CLI.parent / "sim-skills"


@dataclass(frozen=True)
class RegistryEntry:
    name: str
    module_path: str    # e.g. "sim.drivers.coolprop"
    class_name: str     # e.g. "CoolPropDriver"


def parse_registry() -> list[RegistryEntry]:
    src = (SIM_CLI / "src/sim/drivers/__init__.py").read_text(encoding="utf-8")
    out: list[RegistryEntry] = []
    for m in re.finditer(r'\("([^"]+)",\s*"([^"]+):([^"]+)"\)', src):
        out.append(RegistryEntry(m.group(1), m.group(2), m.group(3)))
    return out


def lookup(name: str) -> RegistryEntry:
    for r in parse_registry():
        if r.name == name:
            return r
    raise SystemExit(
        f"driver {name!r} not found in _BUILTIN_REGISTRY. "
        f"Registered: {[r.name for r in parse_registry()]}"
    )


def driver_dir(entry: RegistryEntry) -> Path:
    rel = entry.module_path.replace(".", "/")
    return SIM_CLI / "src" / rel


def skill_dir(name: str) -> Path:
    return SIM_SKILLS / name


def fixtures_for(name: str) -> list[Path]:
    """Match any test fixture starting with ``<name>_``, regardless of suffix.

    coolprop fixtures are ``.py`` files; ltspice fixtures are ``.net`` files;
    other drivers may ship ``.json`` / ``.csv`` / etc. The previous glob was
    ``<name>_*.py`` and silently dropped non-``.py`` fixtures.
    """
    fixtures_dir = SIM_CLI / "tests/fixtures"
    return sorted(
        p for p in fixtures_dir.glob(f"{name}_*")
        if p.is_file() and "__pycache__" not in p.parts
    )


def driver_tests_dir(name: str) -> Path:
    return SIM_CLI / "tests/drivers" / name


def execution_dir(name: str) -> Path:
    return SIM_CLI / "tests/execution" / name


# ── Plugin tree assembly ────────────────────────────────────────────────────


PYPROJECT_TEMPLATE = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sim-plugin-{name}"
version = "0.1.0"
description = "{summary}"
readme = "README.md"
license = "Apache-2.0"
requires-python = ">=3.10"
authors = [{{ name = "Weiqi Ji", email = "jiweiqi10@gmail.com" }}]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "Topic :: Scientific/Engineering",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "License :: OSI Approved :: Apache Software License",
]
dependencies = [
    "sim-runtime @ git+https://github.com/svd-ai-lab/sim-cli@{sim_runtime_pin}",
{extra_deps}
]

[project.optional-dependencies]
test = [
    "pytest>=7",
    "build>=1.0",
]

[project.entry-points."sim.drivers"]
{name} = "sim_plugin_{name}:{class_name}"

[project.entry-points."sim.skills"]
{name} = "sim_plugin_{name}:skills_dir"

[project.entry-points."sim.plugins"]
{name} = "sim_plugin_{name}:plugin_info"

[project.urls]
Homepage = "https://github.com/svd-ai-lab/sim-plugin-{name}"
Issues = "https://github.com/svd-ai-lab/sim-plugin-{name}/issues"

[tool.hatch.metadata]
# Required because `sim-runtime` is pinned to a git+https URL — sim-cli is
# distributed via GitHub, not PyPI. See sim-proj memory: plugin distribution
# is GitHub-only.
allow-direct-references = true

[tool.hatch.build.targets.wheel]
packages = ["src/sim_plugin_{name}"]
"""


INIT_TEMPLATE = '''\
"""{display_name} driver plugin for sim-cli.

Distributed as an out-of-tree plugin; discovered by sim-cli via the
``sim.drivers`` entry-point group. Bundled skill files (under
``_skills/``) are exposed via the ``sim.skills`` entry-point group, and
lightweight metadata via ``sim.plugins``.
"""
from importlib.resources import files

from .driver import {class_name}

skills_dir = files(__name__) / "_skills"

plugin_info = {{
    "name": "{name}",
    "summary": "{summary}",
    "homepage": "https://github.com/svd-ai-lab/sim-plugin-{name}",
    "license_class": "oss",
    "solver_name": "{display_name}",
}}

__all__ = ["{class_name}", "skills_dir", "plugin_info"]
'''


TEST_PROTOCOL_TEMPLATE = '''\
"""Protocol-conformance test — plugged into sim-cli's shared harness."""
from __future__ import annotations

from sim.testing import assert_protocol_conformance
from sim_plugin_{name} import {class_name}


def test_protocol_conformance() -> None:
    """Drives every conformance check sim-cli requires of a plugin driver."""
    assert_protocol_conformance({class_name})
'''


TEST_WHEEL_CONTENTS_TEMPLATE = '''\
"""Build the wheel and assert that bundled skill files actually ship.

This locks the layout decision: ``_skills/`` lives inside the package, so
hatchling picks it up via ``packages = ["src/sim_plugin_{name}"]``
without any ``force-include`` clause. If a future refactor moves
``_skills/`` outside the package, this test fails immediately.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_wheel_contains_skills(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    out_dir.mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"build failed: {{proc.stderr[-2000:]}}"

    wheels = list(out_dir.glob("sim_plugin_{name}-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {{wheels}}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())

    required = {{
        "sim_plugin_{name}/__init__.py",
        "sim_plugin_{name}/driver.py",
        "sim_plugin_{name}/_skills/{name}/SKILL.md",
    }}
    missing = required - names
    assert not missing, f"missing from wheel: {{missing}}"
'''


GITIGNORE = """\
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.venv/
.pytest_cache/
.ruff_cache/
.uv/
"""


def _slurp(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write(p: Path, content: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"  [dry-run] would write {p}  ({len(content)} bytes)")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _copy_tree(src: Path, dst: Path, dry_run: bool = False) -> None:
    if not src.exists():
        return
    if dry_run:
        for child in sorted(src.rglob("*")):
            if child.is_file():
                rel = child.relative_to(src)
                print(f"  [dry-run] would copy {rel}")
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _copy_file(src: Path, dst: Path, dry_run: bool = False) -> None:
    if not src.is_file():
        return
    if dry_run:
        print(f"  [dry-run] would copy {src.name}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _rewrite_imports(text: str, name: str) -> str:
    """Convert sim-cli test imports + string-form module paths to plugin paths.

    Handles three forms:

    1. Statement imports (with submodule):
         from sim.drivers.coolprop.driver import CoolPropDriver
       -> from sim_plugin_coolprop.driver import CoolPropDriver

    2. Statement imports (top-level only):
         from sim.drivers.coolprop import CoolPropDriver
       -> from sim_plugin_coolprop import CoolPropDriver

    3. String paths inside ``monkeypatch.setattr(...)`` etc.:
         "sim.drivers.coolprop.driver.run_net"
       -> "sim_plugin_coolprop.driver.run_net"

    Form (3) is essential for tests that patch private helpers via the
    string form of ``importlib``-style paths. Without it, monkeypatch
    silently no-ops because the original module never existed under its
    sim-cli name in the plugin venv.
    """
    sub = name  # short alias for readability inside the lambdas

    # Form 1 + 2 — statement-level imports.
    text = re.sub(
        rf"from\s+sim\.drivers\.{re.escape(sub)}\.(\w+)\s+import",
        rf"from sim_plugin_{sub}.\1 import",
        text,
    )
    text = re.sub(
        rf"from\s+sim\.drivers\.{re.escape(sub)}\s+import",
        f"from sim_plugin_{sub} import",
        text,
    )

    # Form 3 — string-form dotted paths inside calls (monkeypatch, importlib,
    # patch decorators, etc.). Match within quoted strings only.
    text = re.sub(
        rf"\bsim\.drivers\.{re.escape(sub)}\b",
        f"sim_plugin_{sub}",
        text,
    )

    return text


# ── Inferred metadata ──────────────────────────────────────────────────────


def infer_summary(entry: RegistryEntry) -> str:
    """Pull the one-line summary from the driver module's docstring.

    Falls back to a generic line.
    """
    src = (driver_dir(entry) / "driver.py").read_text(encoding="utf-8")
    m = re.search(r'^"""([^\n]+)\n', src)
    if m:
        return m.group(1).rstrip(".") + "."
    return f"{entry.name} driver for sim-cli."


def infer_display_name(entry: RegistryEntry) -> str:
    """Best-effort display name. Falls back to the registry name."""
    return entry.class_name.replace("Driver", "") or entry.name.title()


def collect_extra_deps(entry: RegistryEntry) -> str:
    """Detect the SDK package the driver imports.

    For now, we leave this empty — the codemod produces a placeholder line
    that a human fills in. Auto-detection is fragile (some drivers use
    importlib, some use shelling-out, some use the user's own venv).
    """
    return f'    # TODO(reviewer): pin the {entry.name} SDK here, e.g. "{entry.name}>=X.Y"'


# ── Main ───────────────────────────────────────────────────────────────────


def assemble_plugin(entry: RegistryEntry, output: Path, sim_runtime_pin: str,
                     dry_run: bool) -> None:
    summary = infer_summary(entry)
    display_name = infer_display_name(entry)
    extra_deps = collect_extra_deps(entry)

    pkg = output / "src" / f"sim_plugin_{entry.name}"
    _write(pkg / "__init__.py", INIT_TEMPLATE.format(
        name=entry.name, class_name=entry.class_name,
        display_name=display_name, summary=summary,
    ), dry_run=dry_run)

    # Copy driver.py into the plugin package.
    _copy_file(driver_dir(entry) / "driver.py", pkg / "driver.py", dry_run=dry_run)
    # Copy compatibility.yaml if present.
    compat = driver_dir(entry) / "compatibility.yaml"
    if compat.is_file():
        _copy_file(compat, pkg / "compatibility.yaml", dry_run=dry_run)

    # Skills: copy ../sim-skills/<name>/* into _skills/<name>/.
    _copy_tree(skill_dir(entry.name), pkg / "_skills" / entry.name, dry_run=dry_run)

    # Tests: copy tests/drivers/<name>/* (rewriting imports) + fixtures + execution.
    src_tests = driver_tests_dir(entry.name)
    if src_tests.exists():
        for f in sorted(src_tests.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            rel = f.relative_to(src_tests)
            text = _rewrite_imports(_slurp(f), entry.name)
            _write(output / "tests" / rel, text, dry_run=dry_run)

    for f in fixtures_for(entry.name):
        _copy_file(f, output / "fixtures" / f.name, dry_run=dry_run)
    not_sim = SIM_CLI / "tests/fixtures/not_simulation.py"
    if not_sim.is_file():
        _copy_file(not_sim, output / "fixtures/not_simulation.py", dry_run=dry_run)

    if execution_dir(entry.name).exists():
        for f in sorted(execution_dir(entry.name).rglob("*.py")):
            rel = f.relative_to(execution_dir(entry.name))
            _copy_file(f, output / "tests" / rel, dry_run=dry_run)

    # Add canonical plugin-side tests on top of the lifted tests.
    _write(output / "tests/__init__.py", "", dry_run=dry_run)
    _write(output / "tests/test_protocol.py", TEST_PROTOCOL_TEMPLATE.format(
        name=entry.name, class_name=entry.class_name,
    ), dry_run=dry_run)
    _write(output / "tests/test_wheel_contents.py", TEST_WHEEL_CONTENTS_TEMPLATE.format(
        name=entry.name,
    ), dry_run=dry_run)

    # Plumbing files.
    _write(output / "pyproject.toml", PYPROJECT_TEMPLATE.format(
        name=entry.name, class_name=entry.class_name, summary=summary,
        sim_runtime_pin=sim_runtime_pin, extra_deps=extra_deps,
    ), dry_run=dry_run)
    _write(output / ".gitignore", GITIGNORE, dry_run=dry_run)
    _write(output / "README.md", _readme_for(entry.name, display_name, summary), dry_run=dry_run)

    # LICENSE — copy from sim-cli's own LICENSE file (Apache-2.0).
    license_src = SIM_CLI / "LICENSE"
    if license_src.is_file():
        _copy_file(license_src, output / "LICENSE", dry_run=dry_run)


def _readme_for(name: str, display_name: str, summary: str) -> str:
    return f"""\
# sim-plugin-{name}

{display_name} driver for [sim-cli](https://github.com/svd-ai-lab/sim-cli),
distributed as an out-of-tree plugin.

{summary}

## Install

```bash
sim plugin install {name}
```

Other paths:

```bash
pip install git+https://github.com/svd-ai-lab/sim-plugin-{name}@v0.1.0
pip install https://github.com/svd-ai-lab/sim-plugin-{name}/releases/download/v0.1.0/sim_plugin_{name}-0.1.0-py3-none-any.whl
pip install -e .
```

After install:

```bash
sim plugin doctor {name}
sim plugin sync-skills
```

## Development

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-{name}
cd sim-plugin-{name}
uv sync
uv run pytest
```

## License

Apache-2.0.
"""


def removal_plan(entry: RegistryEntry) -> list[str]:
    """List what the post-extraction sim-cli + sim-skills cleanup PR removes."""
    out = [
        f"sim-cli:    rm -rf src/sim/drivers/{entry.name}/",
        f"sim-cli:    rm -rf tests/drivers/{entry.name}/",
        f"sim-cli:    rm tests/fixtures/{entry.name}_*",
        f"sim-cli:    rm -rf tests/execution/{entry.name}/  (if present)",
        f"sim-cli:    drop the registry row for {entry.name!r} in src/sim/drivers/__init__.py",
        f"sim-skills: rm -rf {entry.name}/",
        f"sim-plugin-index: append the {entry.name!r} entry (git only first; latest_wheel_url after release)",
    ]
    return out


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("driver", help="driver name (must be in _BUILTIN_REGISTRY)")
    p.add_argument("--output", "-o", required=True, help="output dir for the plugin tree")
    p.add_argument("--dry-run", action="store_true", help="don't write anything; just describe")
    p.add_argument(
        "--sim-runtime-pin",
        default=_default_sim_runtime_pin(),
        help="git ref to pin sim-runtime to in the plugin's pyproject (default: current sim-cli main commit)",
    )
    return p.parse_args(argv)


def _default_sim_runtime_pin() -> str:
    """Resolve a default pin: latest tag if available, otherwise main commit."""
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=SIM_CLI, text=True,
        ).strip()
        if tag:
            return tag
    except subprocess.CalledProcessError:
        pass
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "main"],
        cwd=SIM_CLI, text=True,
    ).strip()


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    entry = lookup(args.driver)
    output = Path(args.output).resolve()

    print(f"[extract] driver={entry.name} class={entry.class_name}")
    print(f"[extract] output={output}")
    print(f"[extract] sim-runtime pin={args.sim_runtime_pin}")
    print(f"[extract] dry-run={args.dry_run}")
    print()

    assemble_plugin(entry, output, args.sim_runtime_pin, dry_run=args.dry_run)

    print()
    print("[extract] sim-cli + sim-skills + sim-plugin-index removal plan:")
    for line in removal_plan(entry):
        print(f"  {line}")
    print()
    print("[extract] next manual steps (human-gated):")
    print("  1. cd <output> && uv venv .venv-build && uv pip install build hatchling")
    print("     uv run python -m build --wheel  # verify wheel ships _skills/<driver>/SKILL.md")
    print("  2. uv venv .venv-test --python 3.12")
    print("     uv pip install --python .venv-test/bin/python -e ../sim-cli ./<output>")
    print("     uv pip install pytest && uv run pytest tests/test_protocol.py -q")
    print("  3. gh repo create svd-ai-lab/sim-plugin-<name> --public")
    print("  4. open the three coordinated PRs (sim-cli removal, sim-skills removal, index entry)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
