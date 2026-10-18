# Inspect active reacting-flow scalar boundary fields.
#
# Optional globals:
#   VELOCITY_INLET_NAMES: list of inlet names to inspect. If omitted, all
#     available velocity inlets are inspected when PyFluent exposes names.
#   PRESSURE_OUTLET_NAMES: list of outlet names to inspect.


def _object_names(group):
    for attr in ("get_object_names", "keys"):
        fn = getattr(group, attr, None)
        if callable(fn):
            try:
                return list(fn())
            except Exception:
                pass
    try:
        return list(group.child_names)
    except Exception:
        return []


def _child_names(obj):
    try:
        return list(obj.child_names)
    except Exception as exc:
        return [f"{type(exc).__name__}: {exc}"]


def _state(obj):
    try:
        return obj()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


bc = solver.setup.boundary_conditions
velocity_inlet_names = globals().get(
    "VELOCITY_INLET_NAMES",
    _object_names(bc.velocity_inlet),
)
pressure_outlet_names = globals().get(
    "PRESSURE_OUTLET_NAMES",
    _object_names(bc.pressure_outlet),
)

inlets = {}
for name in velocity_inlet_names:
    inlet = bc.velocity_inlet[name]
    inlets[name] = {
        "children": _child_names(inlet),
        "species_children": _child_names(inlet.species),
        "species_state": _state(inlet.species),
    }

outlets = {}
for name in pressure_outlet_names:
    outlet = bc.pressure_outlet[name]
    outlets[name] = {
        "children": _child_names(outlet),
        "species_children": _child_names(outlet.species),
        "species_state": _state(outlet.species),
    }

_result = {
    "step": "inspect-reacting-bc-scalars",
    "velocity_inlets": inlets,
    "pressure_outlets": outlets,
    "ok": True,
}
