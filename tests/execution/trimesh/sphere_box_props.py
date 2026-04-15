"""Trimesh E2E — geometric properties of standard primitives.

Box(2, 3, 4): V_analytical = 24, A = 52
Sphere(r=1, subdiv=4): V≈4/3π≈4.189, A≈4π≈12.566
   With finite tessellation, expect ~1-2% error.

Acceptance:
- box: exact (machine precision)
- sphere: rel error < 5%
"""
import json
import math
import trimesh


def main():
    box = trimesh.creation.box(extents=[2.0, 3.0, 4.0])
    sphere = trimesh.creation.icosphere(subdivisions=4, radius=1.0)

    box_v_err = abs(box.volume - 24.0) / 24.0
    box_a_err = abs(box.area - 52.0) / 52.0

    sph_v_th = 4/3 * math.pi
    sph_a_th = 4 * math.pi
    sph_v_err = abs(sphere.volume - sph_v_th) / sph_v_th
    sph_a_err = abs(sphere.area - sph_a_th) / sph_a_th

    print(json.dumps({
        "ok": bool(box_v_err < 1e-10 and box_a_err < 1e-10 and
                   sph_v_err < 0.05 and sph_a_err < 0.05),
        "box_volume": float(box.volume),
        "box_area": float(box.area),
        "sphere_volume": float(sphere.volume), "sphere_volume_theory": sph_v_th,
        "sphere_area": float(sphere.area), "sphere_area_theory": sph_a_th,
        "sphere_watertight": bool(sphere.is_watertight),
    }))


if __name__ == "__main__":
    main()
