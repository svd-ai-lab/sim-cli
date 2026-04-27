# Step 01: Smoke test — verify Workbench session is responsive.
# Preconditions: sim connect --solver workbench succeeded.
# Acceptance: IronPython executes without error.

import json, os, codecs

out = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "step": "smoke-test", "msg": "workbench alive"}))
f.close()
