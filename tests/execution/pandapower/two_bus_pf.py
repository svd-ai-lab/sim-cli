"""pandapower E2E — 2-bus power flow.

Slack at b1 (20 kV), 10 km LV line to b2, 0.5 MW load.
Acceptance:
- Power flow converges
- vm_pu at b2 in [0.95, 1.0]  (small voltage drop expected)
- losses positive but small (<10 kW)
"""
import json
import pandapower as pp


def main():
    net = pp.create_empty_network()
    b1 = pp.create_bus(net, vn_kv=20.0)
    b2 = pp.create_bus(net, vn_kv=20.0)
    pp.create_ext_grid(net, b1)
    pp.create_line(net, b1, b2, length_km=10, std_type="NAYY 4x150 SE")
    pp.create_load(net, b2, p_mw=0.5)

    pp.runpp(net)
    vm = float(net.res_bus.vm_pu[b2])
    losses = float(net.res_line.pl_mw.sum())
    print(json.dumps({
        "ok": 0.95 <= vm <= 1.0 and 0 < losses < 0.01,
        "vm_pu_b2": vm,
        "loss_mw": losses,
        "converged": True,
    }))


if __name__ == "__main__":
    main()
