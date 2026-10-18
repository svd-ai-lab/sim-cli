# Step 04: Execute an IronPython journal that creates a Modal analysis.
# Preconditions: Workbench session alive.
# Acceptance: Modal system created with correct template name.

SetScriptVersion(Version="24.1")

template1 = GetTemplate(TemplateName="Modal", Solver="ANSYS")
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
    "step": "run-journal-modal",
    "system_type": "Modal",
    "components": components,
    "component_count": len(components),
}))
f.close()
