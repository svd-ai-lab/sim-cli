"""Select one plugin distribution from a tag or workflow input."""
import argparse
import os
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def select(tag=None, package=None):
    if tag:
        match = re.fullmatch(r"([a-z]+)-v([0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]*)?)", tag)
        if not match:
            raise ValueError("invalid plugin release tag")
        solver, version = match.groups()
        if package and package != solver:
            raise ValueError("tag and package disagree")
    else:
        solver, version = package, None
    if not solver or not re.fullmatch(r"[a-z]+", solver):
        raise ValueError("select a plugin package")
    directory = ROOT / "plugins" / solver
    project = tomllib.loads((directory / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project["name"] != "sim-plugin-" + solver or (version and version != project["version"]):
        raise ValueError("release tag does not match package metadata")
    return {"project": "plugins/" + solver, "package": project["name"], "solver": solver}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--package")
    args = parser.parse_args()
    selected = select(args.tag, args.package)
    content = "".join(f"{key}={value}\n" for key, value in selected.items())
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(content)
    print(content, end="")


if __name__ == "__main__":
    main()
