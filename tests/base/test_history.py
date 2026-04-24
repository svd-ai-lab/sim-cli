"""Tests for sim history — global append-only jsonl store.

Replaces the old .sim/runs/NNN.json tests. The RunStore class was
removed alongside issue #5 (moved to ~/.sim/history.jsonl).
"""
import json

from sim import config as _cfg, history as _history


class TestHistory:
    def test_append_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        run_id = _history.append({
            "solver": "pybamm",
            "kind": "run",
            "label": "t.py",
            "ok": True,
            "duration_ms": 1500,
        })
        assert run_id == "001"
        path = _cfg.history_path()
        assert path.is_file()
        line = path.read_text(encoding="utf-8").splitlines()[-1]
        rec = json.loads(line)
        assert rec["solver"] == "pybamm"
        assert rec["run_id"] == "001"
        assert rec["ok"] is True
        assert rec["cwd"]  # always populated

    def test_append_fills_schema_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        _history.append({"solver": "pybamm", "ok": True})
        rec = _history.read()[0]
        # All required schema fields present
        for field in ("ts", "cwd", "session_id", "solver", "run_id",
                      "kind", "label", "ok", "duration_ms"):
            assert field in rec

    def test_read_returns_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        _history.append({"solver": "pybamm", "label": "a", "ok": True})
        _history.append({"solver": "pybamm", "label": "b", "ok": True})
        runs = _history.read()
        assert len(runs) == 2
        assert runs[0]["label"] == "b"
        assert runs[1]["label"] == "a"

    def test_filter_by_solver(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        _history.append({"solver": "pybamm", "ok": True})
        _history.append({"solver": "fluent", "ok": True})
        assert len(_history.read(solver="pybamm")) == 1
        assert len(_history.read(solver="fluent")) == 1
        assert len(_history.read()) == 2

    def test_filter_by_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        _history.append({"solver": "pybamm", "session_id": "s-1", "ok": True})
        _history.append({"solver": "pybamm", "session_id": "s-2", "ok": True})
        _history.append({"solver": "pybamm", "session_id": "", "ok": True})
        assert len(_history.read(session_id="s-1")) == 1

    def test_filter_by_cwd(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        d1 = tmp_path / "proj-a"
        d1.mkdir()
        d2 = tmp_path / "proj-b"
        d2.mkdir()
        _history.append({"solver": "pybamm", "cwd": str(d1), "ok": True})
        _history.append({"solver": "pybamm", "cwd": str(d2), "ok": True})
        assert len(_history.read(cwd=d1)) == 1
        assert len(_history.read(cwd=d2)) == 1

    def test_get_by_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        _history.append({"solver": "pybamm", "ok": True})
        rid = _history.append({"solver": "pybamm", "label": "hit", "ok": True})
        rec = _history.get_by_id(rid)
        assert rec is not None
        assert rec["label"] == "hit"

    def test_get_last(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        _history.append({"solver": "pybamm", "label": "first", "ok": True})
        _history.append({"solver": "pybamm", "label": "second", "ok": True})
        rec = _history.get_by_id("last")
        assert rec is not None
        assert rec["label"] == "second"

    def test_run_id_increments(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIM_HOME", str(tmp_path / ".sim"))
        id1 = _history.append({"solver": "pybamm", "ok": True})
        id2 = _history.append({"solver": "pybamm", "ok": True})
        id3 = _history.append({"solver": "pybamm", "ok": True})
        assert id1 == "001"
        assert id2 == "002"
        assert id3 == "003"
