"""Minimal Cantera script — gri30 mechanism + adiabatic flame T."""
import json
import cantera as ct

g = ct.Solution('gri30.yaml')
g.TPX = 300.0, ct.one_atm, 'CH4:1, O2:2, N2:7.52'
g.equilibrate('HP')
print(json.dumps({"ok": True, "T_ad_K": float(g.T)}))
