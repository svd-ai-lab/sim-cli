"""Minimal CoolProp script."""
import json
from CoolProp.CoolProp import PropsSI
T_sat = PropsSI('T', 'P', 101325, 'Q', 0, 'Water')
print(json.dumps({"ok": True, "T_sat_K": float(T_sat)}))
