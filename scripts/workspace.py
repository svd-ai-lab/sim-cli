"""Read package metadata and run isolated public test suites."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def packages():
    return [ROOT, *sorted((ROOT / "plugins").iterdir())]


def plugin_index():
    plugins = []
    for directory in packages()[1:]:
        document = tomllib.loads((directory / "pyproject.toml").read_text(encoding="utf-8"))
        project = document["project"]
        path = directory.relative_to(ROOT).as_posix()
        install_spec = project["name"]
        if not document.get("tool", {}).get("sim", {}).get("pypi", True):
            install_spec += " @ git+https://github.com/svd-ai-lab/sim-cli.git#subdirectory=" + path
        plugins.append({
            "solver": directory.name,
            "package": project["name"],
            "version": project["version"],
            "install_spec": install_spec,
            "path": path,
            "repository": "https://github.com/svd-ai-lab/sim-cli",
            "source": "https://github.com/svd-ai-lab/sim-cli/tree/main/" + path,
            "entry_points": project.get("entry-points", {}),
        })
    return {"schema_version": 1, "plugins": plugins}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["index", "test"])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--package", help="core or a solver directory name")
    args = parser.parse_args()
    if args.action == "index":
        content = json.dumps(plugin_index(), indent=2, ensure_ascii=False) + "\n"
        destination = ROOT / "plugin-index.json"
        if args.check:
            if not destination.is_file() or destination.read_text(encoding="utf-8") != content:
                parser.exit(1, "plugin-index.json is stale; run scripts/workspace.py index\n")
        else:
            destination.write_text(content, encoding="utf-8", newline="\n")
        return
    failures = []
    directories = packages()
    if args.package:
        directories = [p for p in directories if ("core" if p == ROOT else p.name) == args.package]
        if not directories:
            parser.error("unknown workspace package")
    for directory in directories:
        name = "core" if directory == ROOT else directory.name
        print(f"=== {name} ===", flush=True)
        command = [sys.executable, "-m", "pytest", "-q", "tests", "-m", "not integration", "--import-mode=importlib"]
        result = subprocess.run(command, cwd=directory, timeout=240)
        if result.returncode:
            failures.append(name)
    if failures:
        parser.exit(1, "Failed: " + ", ".join(failures) + "\n")


if __name__ == "__main__":
    main()
