"""Walk a COMSOL Java model tree and produce a structured summary.

The COMSOL Java API is a near-1:1 mirror of the GUI tree — thousands
of nodes, undocumented type strings, default features auto-created
beside user-created ones. `describe()` reduces that to a typed Python
dict (and a compact text format) so an agent can answer "what's in
this model" without walking the tree by hand each time.

Scope: physics interfaces and their features. Selections, materials,
mesh, and study layers land in follow-up slices.

Read-side API observed against COMSOL 6.4 + Heat Transfer in Solids
(see `tests/inspect/verify_describe_physics.py`):
  - `model.physics().tags()`            → Java string array of physics tags
  - `model.physics(tag).name()`         → display name
  - `model.physics(tag).getType()`      → type string ("HeatTransfer")
  - `phy.feature().tags()`              → all features (user + defaults)
  - `feat.getType()`                    → feature type string
  - `feat.name()`                       → display name
  - `feat.selection().entities()`       → int[] of geometric entity ids
  - `feat.selection().named()`          → named-selection tag, or ""
  - `feat.properties()`                 → string[] of property names
  - `feat.getString(name)`              → property value as string

Selection dimension is intentionally not surfaced: COMSOL's Java
`Selection.dimension()` returned a 4-byte little-endian buffer through
JPype rather than a Python int during probing, so we drop that field
until a reliable accessor is found. Callers can infer dimension from
the feature type ("...Boundary" → 2D in 3D models, "Solid..." → 3D).
"""
from __future__ import annotations

from typing import Any


# Curated highlight properties per feature type — values shown inline in
# `format_text()`. Other properties remain available in the full dict.
_HIGHLIGHT_PROPS: dict[str, tuple[str, ...]] = {
    "TemperatureBoundary": ("T0",),
    "HeatFluxBoundary": ("HeatFluxType", "q0_input", "h", "Text"),
    "HeatSource": ("Q0",),
    "ThinLayer": ("ThinLayerType", "ds", "k_mat"),
    "ThermalInsulation": (),  # default — no useful highlight
    "SolidHeatTransferModel": ("Solid_material", "k", "rho", "Cp"),
    "init": ("Tinit",),
}


def describe(model: Any, what: str = "physics") -> dict[str, Any]:
    """Return a structured summary of the live COMSOL model.

    Parameters
    ----------
    model
        Live COMSOL Java model (the object injected as `model` into a
        `sim exec` snippet). Anything responding to the read-side API
        above will work — unit tests pass a Python stub.
    what
        Currently only ``"physics"`` is implemented. Future scopes:
        ``"selections"``, ``"materials"``, ``"mesh"``, ``"study"``,
        ``"all"``.

    Returns
    -------
    dict
        ``{"what": "physics", "physics": [<interface dict>, ...]}``
        where each interface dict has ``tag`` / ``type`` / ``name`` /
        ``features`` (a list of feature dicts).
    """
    if what != "physics":
        raise ValueError(
            f"describe(): only what='physics' is implemented "
            f"(got {what!r}). Selections / materials / mesh / study "
            f"land in follow-up slices."
        )
    return {"what": "physics", "physics": _walk_physics(model)}


def _walk_physics(model: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tag in _str_list(model.physics().tags()):
        phy = model.physics(tag)
        out.append({
            "tag": tag,
            "type": _safe_str(lambda: phy.getType()),
            "name": _safe_str(lambda: phy.name()),
            "features": _walk_features(phy),
        })
    return out


def _walk_features(phy: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tag in _str_list(phy.feature().tags()):
        feat = phy.feature(tag)
        out.append({
            "tag": tag,
            "type": _safe_str(lambda: feat.getType()),
            "name": _safe_str(lambda: feat.name()),
            "selection_entities": _safe_int_list(lambda: feat.selection().entities()),
            "selection_named": _safe_str(lambda: feat.selection().named()) or None,
            "properties": _read_properties(feat),
        })
    return out


def _read_properties(feat: Any) -> dict[str, str]:
    """Read every property of a feature as a string. Errors are dropped
    silently — a busted property shouldn't sink the whole summary."""
    try:
        names = _str_list(feat.properties())
    except Exception:
        return {}
    out: dict[str, str] = {}
    for n in names:
        try:
            out[n] = str(feat.getString(n))
        except Exception:
            continue
    return out


def _str_list(java_array: Any) -> list[str]:
    """Coerce a Java string array (JPype) to a Python ``list[str]``."""
    return [str(x) for x in java_array]


def _safe_int_list(thunk: Any) -> list[int]:
    """Run ``thunk`` and coerce its iterable result to ``list[int]``,
    or return ``[]`` on failure."""
    try:
        return [int(x) for x in thunk()]
    except Exception:
        return []


def _safe_str(thunk: Any) -> str:
    try:
        return str(thunk())
    except Exception:
        return ""


# ----------------------------------------------------------------------
# Text rendering
# ----------------------------------------------------------------------


def format_text(summary: dict[str, Any]) -> str:
    """Render a `describe()` summary as a compact human-readable block.

    Layout::

        Physics: <tag> (<type>) — "<name>"
          features (<n>):
            <tag>      <type>           "<name>"            entities=[...]    <highlights>
    """
    if summary.get("what") != "physics":
        raise ValueError("format_text(): only physics summaries are supported")

    interfaces = summary.get("physics") or []
    if not interfaces:
        return "(no physics interfaces in model)"

    lines: list[str] = []
    for i, ifc in enumerate(interfaces):
        if i > 0:
            lines.append("")
        lines.append(
            f'Physics: {ifc["tag"]} ({ifc["type"]}) — "{ifc["name"]}"'
        )
        feats = ifc.get("features") or []
        lines.append(f"  features ({len(feats)}):")
        for f in feats:
            lines.append("    " + _format_feature_line(f))
    return "\n".join(lines)


def _format_feature_line(f: dict[str, Any]) -> str:
    tag = f["tag"]
    ftype = f["type"]
    name = f["name"]
    ents = f.get("selection_entities") or []
    sel_named = f.get("selection_named")

    sel_str = ""
    if sel_named:
        sel_str = f'sel="{sel_named}"'
    elif ents:
        sel_str = f"entities={list(ents)}"

    highlights: list[str] = []
    props = f.get("properties") or {}
    for hp in _HIGHLIGHT_PROPS.get(ftype, ()):
        if hp in props:
            highlights.append(f"{hp}={props[hp]}")
    hl_str = " ".join(highlights)

    head = f'{tag:<10} {ftype:<28} "{name}"'
    tail_parts = [p for p in (sel_str, hl_str) if p]
    if not tail_parts:
        return head
    return head + "  " + "  ".join(tail_parts)
