"""Optional real-solver Mechanical health/model-summary smoke.

Run manually on a machine with Mechanical prerequisites available. The script
prints only structured status and avoids committing logs or screenshots.
"""
from __future__ import annotations

import json

from sim_plugin_mechanical import MechanicalDriver


def main() -> None:
    mech = MechanicalDriver()
    info = mech.launch(ui_mode="gui")
    try:
        print(json.dumps({
            "launch_ok": info.get("ok"),
            "health": mech.query("session.health"),
        }))
        result = mech.run(
            "import json\n"
            "analysis = Model.AddStaticStructuralAnalysis()\n"
            "Tree.Refresh()\n"
            "json.dumps({\"ok\": True, \"analyses\": len(Model.Analyses)})",
            label="health-summary-smoke",
        )
        print(json.dumps({
            "run_ok": result.get("ok"),
            "identity": mech.query("mechanical.project.identity"),
            "summary": mech.query("mechanical.model.summary"),
        }))
    finally:
        mech.disconnect()


if __name__ == "__main__":
    main()
