"""Minimal pymoo script."""
import json
from pymoo.problems import get_problem
p = get_problem("zdt1")
print(json.dumps({"ok": True, "n_var": int(p.n_var)}))
