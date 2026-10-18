# Step 02: Create a Static Structural analysis system.
# Preconditions: Workbench session alive (01 passed).
# Acceptance: System has exactly 6 standard components.

SetScriptVersion(Version="24.1")

template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()

components = []
for comp_name in ["Engineering Data", "Geometry", "Model", "Setup", "Solution", "Results"]:
    try:
        container = system1.GetContainer(ComponentName=comp_name)
        components.append(comp_name)
    except:
        pass

import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({
    "ok": len(components) == 6,
    "step": "create-static-structural",
    "components": components,
    "component_count": len(components),
}))
f.close()
