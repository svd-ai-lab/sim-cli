"""Simulation runner — wraps the standard Newton step loop.

Renamed to `sim_loop` so as not to shadow the top-level `sim` package.

This is the same loop every Newton example uses:

    for substep in range(substeps):
        state.clear_forces()
        model.collide(state, contacts)
        solver.step(state_in, state_out, control, contacts, dt)
        state_in, state_out = state_out, state_in

We do NOT capture a CUDA graph here — graph capture is an optional speedup
that examples opt into; the CLI's first-principles loop is the explicit one.
"""
from __future__ import annotations

from typing import Any


def resolve_solver(name: str) -> type:
    import newton  # noqa: PLC0415

    cls = getattr(newton.solvers, name, None)
    if cls is None or not isinstance(cls, type):
        available = ", ".join(sorted(
            n for n in dir(newton.solvers)
            if n.startswith("Solver") and n != "SolverBase"
        ))
        raise ValueError(f"unknown solver '{name}'. Available: {available}")
    return cls


def parse_solver_args(pairs: list[str] | None) -> dict:
    out: dict = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--solver-arg must be key=value, got {pair!r}")
        k, _, v = pair.partition("=")
        out[k.strip()] = _coerce_scalar(v.strip())
    return out


def _coerce_scalar(v: str):
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _instantiate_solver(solver_cls, model, solver_kwargs):
    import inspect  # noqa: PLC0415

    kwargs = dict(solver_kwargs or {})
    sig = inspect.signature(solver_cls.__init__)
    params = sig.parameters
    has_config_param = (
        "config" in params
        and params["config"].default is inspect.Parameter.empty
    )
    if has_config_param and hasattr(solver_cls, "Config"):
        config = solver_cls.Config()
        for k, v in kwargs.items():
            if hasattr(config, k):
                setattr(config, k, v)
            else:
                raise ValueError(
                    f"{solver_cls.__name__}.Config has no field '{k}'"
                )
        return solver_cls(model, config=config)
    return solver_cls(model, **kwargs)


def run_simulation(
    model: Any,
    *,
    solver_name: str,
    num_frames: int,
    fps: float,
    substeps: int,
    solver_kwargs: dict | None = None,
) -> Any:
    """Run the standard Newton step loop and return the final State."""
    import warp as wp  # noqa: PLC0415

    import newton  # noqa: PLC0415

    solver_cls = resolve_solver(solver_name)
    solver = _instantiate_solver(solver_cls, model, solver_kwargs)

    newton.eval_fk(model, model.joint_q, model.joint_qd, model)

    state_in = model.state()
    state_out = model.state()
    control = model.control()
    contacts = model.contacts()

    frame_dt = 1.0 / float(fps)
    sim_dt = frame_dt / substeps

    has_project_outside = hasattr(solver, "project_outside")

    for _frame in range(num_frames):
        for _ in range(substeps):
            state_in.clear_forces()
            model.collide(state_in, contacts)
            solver.step(state_in, state_out, control, contacts, sim_dt)
            if has_project_outside:
                solver.project_outside(state_out, state_out, sim_dt)
            state_in, state_out = state_out, state_in

    wp.synchronize()
    return state_in
