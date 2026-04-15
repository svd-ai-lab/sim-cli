"""Devito E2E — 2D heat diffusion of a point source.

Initial: u=100 at center cell, 0 elsewhere.
PDE: dt_u = alpha * (dx2_u + dy2_u), alpha=0.1.
After 20 explicit time steps with dt=0.001, the peak should diffuse to
~10% of initial. Sum of u (mass) should be conserved (closed BCs).

Acceptance: peak < 30 (significant diffusion), peak > 5 (still localized),
mass within ±10% of initial 100.
"""
import json
import numpy as np
from devito import Grid, TimeFunction, Eq, solve, Operator


def main():
    grid = Grid(shape=(20, 20), extent=(1.0, 1.0))
    u = TimeFunction(name='u', grid=grid, time_order=1, space_order=2)
    u.data[:] = 0.0
    u.data[0, 10, 10] = 100.0
    initial_mass = float(u.data[0].sum())

    eq = Eq(u.dt, 0.1 * (u.dx2 + u.dy2))
    op = Operator([Eq(u.forward, solve(eq, u.forward))])
    op.apply(time_M=20, dt=0.001)

    final = u.data[-1]
    peak = float(final.max())
    mass = float(final.sum())
    mass_err = abs(mass - initial_mass) / initial_mass

    print(json.dumps({
        "ok": bool(5.0 < peak < 30.0 and mass_err < 0.10),
        "peak": peak,
        "initial_mass": initial_mass,
        "final_mass": mass,
        "mass_rel_error": mass_err,
    }))


if __name__ == "__main__":
    main()
