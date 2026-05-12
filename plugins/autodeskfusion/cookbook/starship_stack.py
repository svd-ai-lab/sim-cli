"""Approximate SpaceX Starship/Super Heavy model for Fusion 360 live sessions.

Run from a project environment after the Fusion bridge is active:
    uv run sim exec --file cookbook/starship_stack.py --label starship-stack

Fusion API length values are centimeters here. The model uses a convenient
tabletop scale where 1 cm represents 1 m of the real vehicle.
"""
from __future__ import annotations

import json
import math
import os
import time
import traceback

import adsk.core
import adsk.fusion


STACK_HEIGHT_CM = 123.0
DIAMETER_CM = 9.0
BOOSTER_HEIGHT_CM = 71.0
SHIP_HEIGHT_CM = 52.0
SHIP_CYLINDER_HEIGHT_CM = 44.0
NOSE_HEIGHT_CM = SHIP_HEIGHT_CM - SHIP_CYLINDER_HEIGHT_CM
RADIUS_CM = DIAMETER_CM / 2.0


def _write(payload: dict) -> None:
    path = os.environ.get("SIM_FUSION360_OUT")
    if not path:
        print(json.dumps(payload, sort_keys=True))
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def _appearance(app, design, *needles):
    lowered = [n.lower() for n in needles if n]
    if not lowered:
        return None
    for lib in app.materialLibraries:
        try:
            for candidate in lib.appearances:
                name = candidate.name.lower()
                if all(n in name for n in lowered):
                    existing = design.appearances.itemByName(candidate.name)
                    return existing or design.appearances.addByCopy(candidate, candidate.name)
        except Exception:
            pass
    return None


def _apply(body, appearance):
    if body and appearance:
        try:
            body.appearance = appearance
        except Exception:
            pass
    return body


def _offset_plane(comp, z_cm):
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.xYConstructionPlane,
        adsk.core.ValueInput.createByReal(z_cm),
    )
    return comp.constructionPlanes.add(plane_input)


def _circle_body(comp, plane, name, cx, cy, radius, depth, appearance=None):
    sketch = comp.sketches.add(plane)
    sketch.name = name + "_sketch"
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(cx, cy, 0),
        radius,
    )
    body = comp.features.extrudeFeatures.addSimple(
        sketch.profiles.item(0),
        adsk.core.ValueInput.createByReal(depth),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    ).bodies.item(0)
    body.name = name
    return _apply(body, appearance)


def _rect_body(comp, plane, name, cx, cy, sx, sy, depth, appearance=None):
    sketch = comp.sketches.add(plane)
    sketch.name = name + "_sketch"
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(cx - sx / 2, cy - sy / 2, 0),
        adsk.core.Point3D.create(cx + sx / 2, cy + sy / 2, 0),
    )
    body = comp.features.extrudeFeatures.addSimple(
        sketch.profiles.item(0),
        adsk.core.ValueInput.createByReal(depth),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    ).bodies.item(0)
    body.name = name
    return _apply(body, appearance)


def _cylinder(comp, name, z_base, height, radius, appearance=None, cx=0.0, cy=0.0):
    return _circle_body(comp, _offset_plane(comp, z_base), name, cx, cy, radius, height, appearance)


def _ring(comp, name, z_base, appearance=None):
    return _cylinder(comp, name, z_base, 0.25, RADIUS_CM + 0.10, appearance)


def _engine_positions():
    positions = [(0.0, 0.0)]
    for ring_radius, count in ((1.35, 6), (2.65, 12), (3.65, 14)):
        for i in range(count):
            angle = 2 * math.pi * i / count
            positions.append((ring_radius * math.cos(angle), ring_radius * math.sin(angle)))
    return positions[:33]


def run(context):
    started = time.time()
    try:
        app = adsk.core.Application.get()
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            _write({"ok": False, "error": "active product is not a Fusion design"})
            return

        root = design.rootComponent
        root.name = "sim_starship_stack"

        stainless = _appearance(app, design, "steel") or _appearance(app, design, "aluminum")
        dark = _appearance(app, design, "black") or _appearance(app, design, "dark")
        copper = _appearance(app, design, "copper") or _appearance(app, design, "orange")
        blue = _appearance(app, design, "blue")

        _cylinder(root, "super_heavy_booster_71m", 0.0, BOOSTER_HEIGHT_CM, RADIUS_CM, stainless)
        _cylinder(root, "starship_upper_stage_44m_body", BOOSTER_HEIGHT_CM, SHIP_CYLINDER_HEIGHT_CM, RADIUS_CM, stainless)
        _cylinder(root, "hot_stage_interstage", BOOSTER_HEIGHT_CM, 2.0, RADIUS_CM + 0.08, dark)

        for i in range(8):
            z_base = BOOSTER_HEIGHT_CM + SHIP_CYLINDER_HEIGHT_CM + i
            radius = max(0.18, RADIUS_CM * (1.0 - (i + 0.5) / 8.0))
            _cylinder(root, f"starship_nose_segment_{i + 1}", z_base, 1.0, radius, stainless)

        for i, z in enumerate((4.5, 18.0, 36.0, 54.0, BOOSTER_HEIGHT_CM, 95.0, 115.0), start=1):
            _ring(root, f"reference_band_{i}", z, dark if z == BOOSTER_HEIGHT_CM else blue)

        for i, (x, y) in enumerate(_engine_positions(), start=1):
            _cylinder(root, f"raptor_engine_{i:02d}", -1.2, 1.2, 0.24, copper, cx=x, cy=y)

        fin_plane = _offset_plane(root, 62.0)
        for i, (cx, cy, sx, sy) in enumerate((
            (RADIUS_CM + 1.2, 0.0, 2.7, 0.35),
            (-(RADIUS_CM + 1.2), 0.0, 2.7, 0.35),
            (0.0, RADIUS_CM + 1.2, 0.35, 2.7),
            (0.0, -(RADIUS_CM + 1.2), 0.35, 2.7),
        ), start=1):
            _rect_body(root, fin_plane, f"super_heavy_grid_fin_{i}", cx, cy, sx, sy, 2.0, dark)

        for z, label in ((BOOSTER_HEIGHT_CM + 4.0, "aft"), (BOOSTER_HEIGHT_CM + 34.0, "forward")):
            flap_plane = _offset_plane(root, z)
            _rect_body(root, flap_plane, f"starship_{label}_flap_port", RADIUS_CM + 0.9, 0.0, 2.2, 0.34, 4.8, dark)
            _rect_body(root, flap_plane, f"starship_{label}_flap_starboard", -(RADIUS_CM + 0.9), 0.0, 2.2, 0.34, 4.8, dark)

        viewport = app.activeViewport
        if viewport:
            viewport.fit()
            viewport.refresh()

        body_names = [root.bRepBodies.item(i).name for i in range(root.bRepBodies.count)]
        _write({
            "ok": True,
            "model": "spacex-starship-super-heavy-approx",
            "scale": "1 cm = 1 m",
            "stack_height_m": STACK_HEIGHT_CM,
            "diameter_m": DIAMETER_CM,
            "booster_height_m": BOOSTER_HEIGHT_CM,
            "ship_height_m": SHIP_HEIGHT_CM,
            "document_name": app.activeDocument.name if app.activeDocument else None,
            "root_component": root.name,
            "body_count": root.bRepBodies.count,
            "sketch_count": root.sketches.count,
            "contains": body_names,
            "elapsed_s": round(time.time() - started, 3),
        })
    except Exception:
        _write({
            "ok": False,
            "model": "spacex-starship-super-heavy-approx",
            "error": traceback.format_exc(),
            "elapsed_s": round(time.time() - started, 3),
        })
