"""Minimal pandapower script."""
import json
import pandapower as pp
net = pp.create_empty_network()
b = pp.create_bus(net, vn_kv=20.0)
print(json.dumps({"ok": True, "n_bus": int(len(net.bus))}))
