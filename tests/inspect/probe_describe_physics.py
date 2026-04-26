"""Win1 verification gate for `sim.drivers.comsol.lib.describe(model)`.

Builds the `block_with_hole` physics tree in a fresh COMSOL session,
calls `describe(model)` and `format_text(summary)` from inside the
session, and asserts the structural shape of the output matches what
the unit-test fixture in `tests/drivers/comsol/test_describe.py`
expects.

The unit tests run on macOS against a hand-rolled Python stand-in, so
they verify the formatter logic but cannot catch JPype/Java contract
drift (e.g., a method renamed in COMSOL 6.x). This probe closes that
gap on a host with COMSOL installed.

Run:
    cd C:/Users/<user>/Documents/GitHub/sim-cli
    .venv/Scripts/python.exe tests/inspect/probe_describe_physics.py

Output:
    tests/inspect/_run_outputs/probe_describe_physics.json
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_ROOT = (
    REPO_ROOT.parent / "sim-skills" / "comsol" / "base" / "workflows"
    / "block_with_hole"
)
OUT_DIR = REPO_ROOT / "tests" / "inspect" / "_run_outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "probe_describe_physics.json"

BASE = os.environ.get("SIM_BASE", "http://localhost:7600")


def post(path: str, body: dict, timeout: float = 180) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def exec_snippet(code: str, label: str) -> dict:
    print(f"[exec] {label} ({len(code)} bytes)")
    resp = post("/exec", {"code": code, "label": label})
    data = resp.get("data") or resp
    if not data.get("ok"):
        print(f"  FAILED: {data.get('error') or data.get('stderr', '')[:500]}")
        sys.exit(1)
    return data


PROBE = r"""
import json
from sim.drivers.comsol.lib import describe, format_text

summary = describe(model, what="physics")
text = format_text(summary)

print("=== format_text() ===")
print(text)
print()
print("=== summary JSON ===")
print("DESCRIBE_BEGIN")
print(json.dumps(summary, indent=2, default=str))
print("DESCRIBE_END")
_result = {"summary": summary, "text": text}
"""


def main() -> int:
    print(f"[connect] {BASE}/connect -> comsol server-only")
    r = post(
        "/connect",
        {"solver": "comsol", "mode": "solver", "ui_mode": "server", "processors": 2},
        timeout=120,
    )
    data = r.get("data") or r
    if not r.get("ok", True):
        print(f"  CONNECT FAILED: {r}")
        return 1
    print(f"  ok — model_tag={data.get('model_tag')}")

    rc = 0
    try:
        for fname in (
            "00_create_geometry.py",
            "01_assign_material.py",
            "02_setup_physics.py",
        ):
            code = (SKILLS_ROOT / fname).read_text(encoding="utf-8")
            exec_snippet(code, fname)

        out = exec_snippet(PROBE, "describe_physics_probe")
        stdout = out.get("stdout", "")
        if "DESCRIBE_BEGIN" in stdout:
            block = stdout.split("DESCRIBE_BEGIN", 1)[1].split("DESCRIBE_END")[0].strip()
            summary = json.loads(block)
        else:
            print("[fail] no DESCRIBE block in stdout")
            print(stdout[:2000])
            return 1

        # Acceptance: same structural assertions as the unit tests, against
        # the live JPype tree.
        assert summary["what"] == "physics", summary
        ifcs = summary["physics"]
        assert len(ifcs) == 1, f"expected 1 physics interface, got {len(ifcs)}"
        ht = ifcs[0]
        assert ht["tag"] == "ht", ht["tag"]
        assert ht["type"] == "HeatTransfer", ht["type"]
        assert ht["name"] == "Heat Transfer in Solids", ht["name"]

        feat_tags = [f["tag"] for f in ht["features"]]
        for required in ("solid1", "init1", "ins1", "temp1", "temp2", "hf1"):
            assert required in feat_tags, f"missing feature {required} in {feat_tags}"

        temp1 = next(f for f in ht["features"] if f["tag"] == "temp1")
        assert temp1["type"] == "TemperatureBoundary", temp1["type"]
        assert temp1["selection_entities"] == [1], temp1["selection_entities"]
        assert temp1["properties"].get("T0") == "373[K]", temp1["properties"].get("T0")

        hf1 = next(f for f in ht["features"] if f["tag"] == "hf1")
        assert hf1["type"] == "HeatFluxBoundary", hf1["type"]
        assert hf1["selection_entities"] == [7, 8, 9], hf1["selection_entities"]
        assert hf1["properties"].get("h") == "50[W/(m^2*K)]", hf1["properties"].get("h")

        OUT_FILE.write_text(json.dumps(summary, indent=2))
        print(f"\n[saved] {OUT_FILE}")
        print("\nPASS — describe(model) matches unit-test fixture against live model.")
    except AssertionError as exc:
        print(f"\nFAIL — assertion: {exc}")
        rc = 1
    except Exception as exc:
        print(f"\nFAIL — {type(exc).__name__}: {exc}")
        rc = 1
    finally:
        print("\n[disconnect]")
        try:
            post("/disconnect", {}, timeout=30)
        except Exception as e:
            print(f"  disconnect failed: {e}")

    return rc


if __name__ == "__main__":
    sys.exit(main())
