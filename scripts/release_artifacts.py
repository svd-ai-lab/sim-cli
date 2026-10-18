"""Create or verify a source-bound manifest for Python distribution files."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "verify"])
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--manifest", type=Path, default=Path("release-manifest.json"))
    parser.add_argument("--expected-sha256")
    parser.add_argument("--project", type=Path, default=Path("."))
    args = parser.parse_args()
    project = tomllib.loads((args.project / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    files = sorted([*args.dist.glob("*.whl"), *args.dist.glob("*.tar.gz")])
    if not files: raise ValueError("no distribution artifacts")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    value = {"schema_version": 1, "name": project["name"], "version": project["version"], "source_ref": source,
        "files": {p.name: digest(p) for p in files}}
    if args.action == "create":
        args.manifest.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    else:
        if not args.expected_sha256 or digest(args.manifest) != args.expected_sha256:
            raise ValueError("approved artifact manifest hash mismatch")
        if json.loads(args.manifest.read_text()) != value:
            raise ValueError("artifact files or source revision changed")
    print(digest(args.manifest))


if __name__ == "__main__": main()
