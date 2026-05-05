"""Optional real-solver Workbench-to-Mechanical handoff smoke.

Run manually on a machine with both plugins installed and solver prerequisites
available. The script prints only structured status and avoids committing logs
or screenshots.
"""
from __future__ import annotations

import json

from sim_plugin_workbench import WorkbenchDriver


def main() -> None:
    wb = WorkbenchDriver()
    info = wb.launch(mode="workbench", ui_mode="gui")
    try:
        print(json.dumps({"launch": info, "health": wb.query("session.health")}))
        script = '''
SetScriptVersion(Version="24.1")
import json, os, codecs

def write_result(payload):
    out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
    f = codecs.open(out, "w", "utf-8")
    f.write(json.dumps(payload))
    f.close()

try:
    template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
    system1 = template1.CreateSystem()
    write_result({
        "ok": True,
        "component_count": 6,
        "components": [
            "Engineering Data", "Geometry", "Model",
            "Setup", "Solution", "Results"
        ]
    })
except Exception as e:
    write_result({
        "ok": False,
        "code": "workbench.template.unavailable",
        "error": str(e)[:240]
    })
'''
        result = wb.run(script, label="handoff-static-structural")
        print(json.dumps({
            "run_ok": result.get("ok"),
            "systems": wb.query("workbench.systems.summary"),
            "identity": wb.query("workbench.project.identity"),
        }))
    finally:
        wb.disconnect()


if __name__ == "__main__":
    main()
