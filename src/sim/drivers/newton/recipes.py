"""Recipe interpreter — declarative ModelBuilder driver (ported from newton-cli).

A recipe is a JSON document that describes a sequence of `ModelBuilder` method
calls. Each op is dispatched via getattr(builder, op) and its args are coerced
from JSON-friendly shapes (lists, dicts) into the Warp types Newton expects:

  - list of length 3   → wp.vec3
  - list of length 4   → wp.quat   (when the parameter wants a quaternion)
  - {"axis":[x,y,z], "angle":t} → wp.quat_from_axis_angle(...)
  - {"p":[x,y,z], "q":<quat>}   → wp.transform(p=..., q=...)

The recipe IS the model serialization format. To "load a model from disk" we
re-execute its recipe — there is no opaque binary blob.

Schema: accepts both `"newton-cli/recipe/v1"` (back-compat) and
`"sim/newton/recipe/v1"` (sim-native canonical name).
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

RECIPE_SCHEMAS = {"newton-cli/recipe/v1", "sim/newton/recipe/v1"}


class RecipeError(ValueError):
    pass


# ---------------------------------------------------------------------------
# coercion
# ---------------------------------------------------------------------------

def _looks_like_vec3(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(
        isinstance(x, (int, float)) for x in value
    )


def _looks_like_quat_xyzw(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(
        isinstance(x, (int, float)) for x in value
    )


def _looks_like_axis_angle(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) >= {"axis", "angle"}


def _looks_like_transform(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) >= {"p", "q"}


def _to_vec3(v: Any) -> Any:
    import warp as wp  # noqa: PLC0415

    if not _looks_like_vec3(v):
        raise RecipeError(f"expected list of 3 numbers for vec3, got {v!r}")
    return wp.vec3(float(v[0]), float(v[1]), float(v[2]))


def _to_quat(v: Any) -> Any:
    import warp as wp  # noqa: PLC0415

    if _looks_like_quat_xyzw(v):
        return wp.quat(float(v[0]), float(v[1]), float(v[2]), float(v[3]))
    if _looks_like_axis_angle(v):
        axis = _to_vec3(v["axis"])
        return wp.quat_from_axis_angle(axis, float(v["angle"]))
    raise RecipeError(f"expected quat as [x,y,z,w] or {{axis,angle}}, got {v!r}")


def _to_transform(v: Any) -> Any:
    import warp as wp  # noqa: PLC0415

    if not _looks_like_transform(v):
        raise RecipeError(f"expected transform as {{p,q}}, got {v!r}")
    return wp.transform(p=_to_vec3(v["p"]), q=_to_quat(v["q"]))


def _to_shape_cfg(spec: dict) -> Any:
    import newton  # noqa: PLC0415

    cfg = newton.ModelBuilder.ShapeConfig()
    for k, v in spec.items():
        setattr(cfg, k, v)
    return cfg


def _to_heightfield(spec: dict) -> Any:
    import numpy as np  # noqa: PLC0415

    import newton  # noqa: PLC0415

    data = spec["data"]
    if isinstance(data, list):
        data = np.asarray(data, dtype=float)
    return newton.Heightfield(
        data=data,
        nrow=int(spec["nrow"]),
        ncol=int(spec["ncol"]),
        hx=float(spec.get("hx", 1.0)),
        hy=float(spec.get("hy", 1.0)),
        min_z=spec.get("min_z"),
        max_z=spec.get("max_z"),
    )


def _to_mesh_from_usd(spec: dict) -> Any:
    from pxr import Usd  # noqa: PLC0415

    import newton.usd  # noqa: PLC0415

    stage = Usd.Stage.Open(str(spec["path"]))
    prim = stage.GetPrimAtPath(str(spec["prim"]))
    mesh = newton.usd.get_mesh(prim)
    finalize = getattr(mesh, "finalize", None)
    if callable(finalize):
        finalize()
    return mesh


def _to_mesh(spec: dict) -> Any:
    import numpy as np  # noqa: PLC0415

    import newton  # noqa: PLC0415

    verts = np.asarray(spec["vertices"], dtype=np.float32)
    inds = np.asarray(spec["indices"], dtype=np.int32)
    mesh_kwargs = {}
    if "is_solid" in spec:
        mesh_kwargs["is_solid"] = bool(spec["is_solid"])
    if "compute_inertia" in spec:
        mesh_kwargs["compute_inertia"] = bool(spec["compute_inertia"])
    mesh = newton.Mesh(verts, inds, **mesh_kwargs)
    sdf_spec = spec.get("build_sdf")
    if sdf_spec is not None:
        sdf_kwargs: dict = {}
        if "max_resolution" in sdf_spec:
            sdf_kwargs["max_resolution"] = int(sdf_spec["max_resolution"])
        if "narrow_band_range" in sdf_spec:
            nb = sdf_spec["narrow_band_range"]
            sdf_kwargs["narrow_band_range"] = (float(nb[0]), float(nb[1]))
        if "margin" in sdf_spec:
            sdf_kwargs["margin"] = float(sdf_spec["margin"])
        if "scale" in sdf_spec:
            sc = sdf_spec["scale"]
            sdf_kwargs["scale"] = (float(sc[0]), float(sc[1]), float(sc[2]))
        mesh.build_sdf(**sdf_kwargs)
    return mesh


_TAG_HANDLERS = {
    "$shape_cfg": _to_shape_cfg,
    "$heightfield": _to_heightfield,
    "$mesh_from_usd": _to_mesh_from_usd,
    "$mesh": _to_mesh,
}


def _coerce_value(v: Any) -> Any:
    if isinstance(v, dict):
        if len(v) == 1:
            (only_key,) = v.keys()
            if only_key in _TAG_HANDLERS:
                return _TAG_HANDLERS[only_key](v[only_key])
        if _looks_like_transform(v):
            return _to_transform(v)
        if _looks_like_axis_angle(v):
            return _to_quat(v)
    if _looks_like_vec3(v):
        return _to_vec3(v)
    if _looks_like_quat_xyzw(v):
        return _to_quat(v)
    if isinstance(v, list) and len(v) > 0 and all(isinstance(x, list) for x in v):
        if all(_looks_like_vec3(x) for x in v):
            return [_to_vec3(x) for x in v]
        if all(_looks_like_quat_xyzw(x) for x in v):
            return [_to_quat(x) for x in v]
    return v


def _coerce_args(args: dict) -> dict:
    return {k: _coerce_value(v) for k, v in args.items()}


# ---------------------------------------------------------------------------
# special (non-method) recipe ops
# ---------------------------------------------------------------------------

def _op_set_builder_array(builder: Any, args: dict) -> None:
    name = args["name"]
    target = getattr(builder, name)
    if "index" in args:
        target[int(args["index"])] = args["value"]
        return
    if "slice" in args:
        s = args["slice"]
        if not isinstance(s, list) or len(s) not in (2, 3):
            raise RecipeError(
                f"set_builder_array: slice must be [start,stop] or [start,stop,step], got {s!r}"
            )
        start = s[0]
        stop = s[1]
        step = s[2] if len(s) == 3 else None
        target[slice(start, stop, step)] = args["values"]
        return
    if "fill" in args:
        value = args["fill"]
        rng = args.get("range")
        if rng is None:
            start, stop = 0, len(target)
        else:
            start = 0 if rng[0] is None else int(rng[0])
            stop = len(target) if rng[1] is None else int(rng[1])
            if start < 0:
                start += len(target)
            if stop < 0:
                stop += len(target)
        for i in range(start, stop):
            target[i] = value
        return
    raise RecipeError("set_builder_array requires one of 'index', 'slice', 'fill'")


def _op_set_default_joint_cfg(builder: Any, args: dict) -> None:
    cfg = builder.default_joint_cfg
    for k, v in args.items():
        setattr(cfg, k, v)


def _op_set_default_shape_cfg(builder: Any, args: dict) -> None:
    cfg = builder.default_shape_cfg
    for k, v in args.items():
        setattr(cfg, k, v)


def _op_register_mujoco_custom_attributes(builder: Any, args: dict) -> None:
    import newton  # noqa: PLC0415

    newton.solvers.SolverMuJoCo.register_custom_attributes(builder)


def _op_register_solver_custom_attributes(builder: Any, args: dict) -> None:
    import newton  # noqa: PLC0415

    name = args["solver"]
    cls = getattr(newton.solvers, name, None)
    if cls is None:
        raise RecipeError(f"unknown solver '{name}' in newton.solvers")
    if not hasattr(cls, "register_custom_attributes"):
        raise RecipeError(f"{name} has no register_custom_attributes() method")
    cls.register_custom_attributes(builder)


def _op_pin_body(builder: Any, args: dict) -> None:
    import warp as wp  # noqa: PLC0415

    idx = int(args["body"])
    if idx < 0:
        idx += builder.body_count
    builder.body_mass[idx] = 0.0
    builder.body_inv_mass[idx] = 0.0
    builder.body_inertia[idx] = wp.mat33(0.0)
    builder.body_inv_inertia[idx] = wp.mat33(0.0)


def _op_apply_body_inertia_diagonal(builder: Any, args: dict) -> None:
    import numpy as np  # noqa: PLC0415
    import warp as wp  # noqa: PLC0415

    value = float(args["value"])
    eye3 = np.eye(3, dtype=np.float32) * value
    for body in range(builder.body_count):
        cur = np.asarray(builder.body_inertia[body], dtype=np.float32).reshape(3, 3)
        builder.body_inertia[body] = wp.mat33(cur + eye3)


def _op_replicate(builder: Any, args: dict) -> None:
    import newton  # noqa: PLC0415

    sub_recipe = args.get("recipe")
    if not isinstance(sub_recipe, dict):
        raise RecipeError("replicate.args.recipe must be an inline recipe object")
    count = int(args["count"])
    spacing = tuple(args.get("spacing", (0.0, 0.0, 0.0)))

    sub_builder = newton.ModelBuilder()
    _execute_recipe_on_builder(sub_builder, sub_recipe)
    builder.replicate(sub_builder, count, spacing=spacing)


def _op_set_builder_attr(builder: Any, args: dict) -> None:
    name = args["name"]
    if not hasattr(builder, name):
        raise RecipeError(f"set_builder_attr: ModelBuilder has no attribute {name!r}")
    setattr(builder, name, args["value"])


_SPECIAL_OPS = {
    "set_builder_array": _op_set_builder_array,
    "set_builder_attr": _op_set_builder_attr,
    "set_default_joint_cfg": _op_set_default_joint_cfg,
    "set_default_shape_cfg": _op_set_default_shape_cfg,
    "apply_body_inertia_diagonal": _op_apply_body_inertia_diagonal,
    "pin_body": _op_pin_body,
    "register_mujoco_custom_attributes": _op_register_mujoco_custom_attributes,
    "register_solver_custom_attributes": _op_register_solver_custom_attributes,
    "replicate": _op_replicate,
}


def _execute_recipe_on_builder(builder: Any, recipe: dict) -> None:
    schema = recipe.get("schema")
    if schema not in RECIPE_SCHEMAS:
        raise RecipeError(
            f"recipe schema must be one of {sorted(RECIPE_SCHEMAS)}, got {schema!r}"
        )
    ops = recipe.get("ops")
    if not isinstance(ops, list):
        raise RecipeError("recipe.ops must be a list")
    for i, entry in enumerate(ops):
        if not isinstance(entry, dict) or "op" not in entry:
            raise RecipeError(f"op[{i}] must be an object with an 'op' key")
        op_name = entry["op"]
        raw_args = entry.get("args", {})
        if not isinstance(raw_args, dict):
            raise RecipeError(
                f"op[{i}].args must be an object, got {type(raw_args).__name__}"
            )

        if op_name in _SPECIAL_OPS:
            try:
                _SPECIAL_OPS[op_name](builder, raw_args)
            except RecipeError:
                raise
            except Exception as e:
                raise RecipeError(f"op[{i}] ({op_name}): {e}") from e
            continue

        method = getattr(builder, op_name, None)
        if not callable(method):
            raise RecipeError(f"op[{i}]: ModelBuilder has no method {op_name!r}")
        try:
            coerced = _coerce_args(raw_args)
        except RecipeError as e:
            raise RecipeError(f"op[{i}] ({op_name}): {e}") from e
        try:
            method(**coerced)
        except TypeError as e:
            raise RecipeError(f"op[{i}] ({op_name}): {e}") from e


def _apply_mpm_attrs(model: Any, entries: list) -> None:
    import numpy as np  # noqa: PLC0415
    import warp as wp  # noqa: PLC0415

    mpm_ns = getattr(model, "mpm", None)
    if mpm_ns is None:
        raise RecipeError(
            "post_finalize.mpm_attrs requires register_solver_custom_attributes "
            "with solver=SolverImplicitMPM in ops"
        )
    for i, entry in enumerate(entries):
        attr = entry.get("attr")
        if attr is None:
            raise RecipeError(f"mpm_attrs[{i}] missing 'attr'")
        target = getattr(mpm_ns, attr, None)
        if target is None:
            raise RecipeError(
                f"mpm_attrs[{i}]: model.mpm has no attribute {attr!r}"
            )
        raw = entry["value"]
        if isinstance(raw, list) and len(raw) == 3:
            value: Any = wp.vec3(float(raw[0]), float(raw[1]), float(raw[2]))
        else:
            value = float(raw)
        if "range" in entry:
            lo, hi = entry["range"]
            idx_np = np.arange(int(lo), int(hi), dtype=np.int32)
            idx = wp.array(idx_np, dtype=int, device=model.device)
            target[idx].fill_(value)
        elif "indices" in entry:
            idx_np = np.asarray(entry["indices"], dtype=np.int32)
            idx = wp.array(idx_np, dtype=int, device=model.device)
            target[idx].fill_(value)
        else:
            target.fill_(value)


def _apply_post_finalize(model: Any, recipe: dict) -> None:
    post = recipe.get("post_finalize") or {}
    structured = {"mpm_attrs", "model_calls"}
    for k, v in post.items():
        if k in structured:
            continue
        setattr(model, k, v)
    if "mpm_attrs" in post:
        entries = post["mpm_attrs"]
        if not isinstance(entries, list):
            raise RecipeError("post_finalize.mpm_attrs must be a list")
        _apply_mpm_attrs(model, entries)
    if "model_calls" in post:
        calls = post["model_calls"]
        if not isinstance(calls, list):
            raise RecipeError("post_finalize.model_calls must be a list")
        for i, call in enumerate(calls):
            method_name = call.get("method")
            if not isinstance(method_name, str):
                raise RecipeError(f"model_calls[{i}] missing 'method' string")
            method = getattr(model, method_name, None)
            if not callable(method):
                raise RecipeError(
                    f"model_calls[{i}]: model has no method {method_name!r}"
                )
            args = call.get("args", [])
            kwargs = call.get("kwargs", {})
            args = [_coerce_value(a) for a in args]
            kwargs = {k: _coerce_value(v) for k, v in kwargs.items()}
            method(*args, **kwargs)


@contextlib.contextmanager
def _nullctx():
    yield


def build_model_from_recipe(recipe_path: str | Path, *, device: str | None = None) -> Any:
    """Re-execute a recipe and return the finalized Model."""
    import warp as wp  # noqa: PLC0415

    import newton  # noqa: PLC0415

    path = Path(recipe_path)
    recipe = json.loads(path.read_text())
    ctx = wp.ScopedDevice(device) if device else _nullctx()
    with ctx:
        builder = newton.ModelBuilder()
        _execute_recipe_on_builder(builder, recipe)
        model = builder.finalize()
        _apply_post_finalize(model, recipe)
        return model


def write_recipe(recipe_path: str | Path, recipe: dict) -> None:
    Path(recipe_path).write_text(json.dumps(recipe, indent=2))


__all__ = [
    "RECIPE_SCHEMAS",
    "RecipeError",
    "build_model_from_recipe",
    "write_recipe",
]
