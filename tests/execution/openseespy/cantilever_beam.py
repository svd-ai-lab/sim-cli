"""Cantilever beam tip deflection — OpenSeesPy E2E.

Geometry: 2D cantilever, length L=1.0 m, fixed at x=0, tip load P at x=L.
Section: A=1e-2 m^2, I=1e-6 m^4, E=2e11 Pa (steel).
Discretization: 10 linear elastic Euler-Bernoulli beam elements.

Analytical tip deflection (small displacement, Euler-Bernoulli):
    delta = P * L^3 / (3 * E * I)
          = 1000 * 1^3 / (3 * 2e11 * 1e-6)
          = -1.6667e-3 m  (negative = downward)

Acceptance: relative error vs analytical < 1%.
"""
import json
import openseespy.opensees as ops


def main():
    L = 1.0
    P = -1000.0  # downward
    E = 2.0e11
    A = 1.0e-2
    I = 1.0e-6
    n_elem = 10

    ops.wipe()
    ops.model('basic', '-ndm', 2, '-ndf', 3)

    for i in range(n_elem + 1):
        ops.node(i + 1, i * L / n_elem, 0.0)
    ops.fix(1, 1, 1, 1)

    ops.geomTransf('Linear', 1)
    for i in range(n_elem):
        ops.element('elasticBeamColumn', i + 1, i + 1, i + 2, A, E, I, 1)

    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)
    ops.load(n_elem + 1, 0.0, P, 0.0)

    ops.system('BandSPD')
    ops.numberer('RCM')
    ops.constraints('Plain')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    ok = ops.analyze(1)

    tip_uy = ops.nodeDisp(n_elem + 1, 2)
    analytical = P * L ** 3 / (3.0 * E * I)
    rel_err = abs(tip_uy - analytical) / abs(analytical)

    print(json.dumps({
        "ok": ok == 0 and rel_err < 0.01,
        "analyze_status": ok,
        "tip_disp_m": tip_uy,
        "analytical_m": analytical,
        "rel_error": rel_err,
        "n_elem": n_elem,
    }))


if __name__ == "__main__":
    main()
