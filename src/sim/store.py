"""Run storage for sim — persists run records as JSON files."""
from __future__ import annotations

import json
from pathlib import Path

from sim.driver import RunResult


class RunStore:
    def __init__(self, root: Path):
        self.root = root
        self.runs_dir = root / "runs"

    def save(self, run: RunResult, parsed_output: dict | None = None) -> str:
        """Save a run result and return its ID."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = self._next_id()
        record = run.to_dict()
        if parsed_output is not None:
            record["parsed_output"] = parsed_output
        (self.runs_dir / f"{run_id}.json").write_text(
            json.dumps(record, indent=2)
        )
        return run_id

    def list(self) -> list[dict]:
        """List all runs, newest first."""
        if not self.runs_dir.exists():
            return []
        runs = []
        for f in sorted(self.runs_dir.glob("*.json")):
            data = json.loads(f.read_text())
            data["id"] = f.stem
            runs.append(data)
        return runs

    def get(self, run_id: str) -> dict:
        """Get a run by ID. Use 'last' for most recent."""
        if run_id == "last":
            runs = self.list()
            if not runs:
                raise FileNotFoundError("No runs recorded")
            return runs[-1]
        path = self.runs_dir / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Run {run_id} not found")
        data = json.loads(path.read_text())
        data["id"] = run_id
        return data

    def _next_id(self) -> str:
        if not self.runs_dir.exists():
            return "001"
        existing = sorted(self.runs_dir.glob("*.json"))
        if not existing:
            return "001"
        last_num = int(existing[-1].stem)
        return f"{last_num + 1:03d}"
