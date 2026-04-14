"""Headless d3plot visualization via DPF — replaces LS-PrePost screenshot.

Reads the d3plot from a previous E2E run and produces:
  1. dpf_kinetic_energy.png   — KE/IE/TE time series (matplotlib)
  2. dpf_displacement.png      — displacement contour at final state (PyVista)
  3. dpf_summary.json          — extracted scalars for E2E assertions
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
D3PLOT = HERE / "d3plot"


def main() -> int:
    if not D3PLOT.is_file():
        print(f"ERROR: {D3PLOT} not found — run the E2E test first")
        return 1

    # Ensure DPF can find the ANSYS install
    awp_root = Path("E:/Program Files/ANSYS Inc/v241")
    if awp_root.is_dir() and not os.environ.get("AWP_ROOT241"):
        os.environ["AWP_ROOT241"] = str(awp_root)
        print(f"Set AWP_ROOT241={awp_root}")

    import ansys.dpf.core as dpf

    # Start local DPF server pointing at the ANSYS install
    try:
        dpf.start_local_server(ansys_path=str(awp_root))
    except Exception as e:
        print(f"DPF server start failed: {e}")
        return 2

    # Load the d3plot
    ds = dpf.DataSources()
    ds.set_result_file_path(str(D3PLOT), "d3plot")
    model = dpf.Model(ds)

    print("=" * 60)
    print("DPF Model loaded:")
    print(model)
    print("=" * 60)

    # Time axis
    time_data = model.metadata.time_freq_support.time_frequencies.data_as_list
    print(f"Time steps: {len(time_data)}, range: {time_data[0]:.4e} → {time_data[-1]:.4e}")

    # Try global kinetic energy
    summary = {
        "n_states": len(time_data),
        "time_start": time_data[0],
        "time_end": time_data[-1],
    }

    try:
        gke_op = dpf.operators.result.global_kinetic_energy()
        gke_op.inputs.data_sources.connect(ds)
        ke = gke_op.eval().get_field(0).data
        ke_list = list(map(float, ke))
        summary["kinetic_energy"] = {
            "max": max(ke_list),
            "min": min(ke_list),
            "final": ke_list[-1],
        }
        print(f"KE: max={max(ke_list):.4e}, final={ke_list[-1]:.4e}")
    except Exception as e:
        print(f"KE extraction failed: {e}")
        ke_list = None

    try:
        gie_op = dpf.operators.result.global_internal_energy()
        gie_op.inputs.data_sources.connect(ds)
        ie = gie_op.eval().get_field(0).data
        ie_list = list(map(float, ie))
        summary["internal_energy"] = {
            "max": max(ie_list),
            "final": ie_list[-1],
        }
        print(f"IE: max={max(ie_list):.4e}, final={ie_list[-1]:.4e}")
    except Exception as e:
        print(f"IE extraction failed: {e}")
        ie_list = None

    # Displacement at last state
    try:
        import numpy as np
        disp_op = model.results.displacement.on_last_time_freq()
        disp_field = disp_op.eval().get_field(0)
        disp_arr = np.asarray(disp_field.data)  # shape (n_nodes, 3)
        if disp_arr.ndim == 1:
            disp_arr = disp_arr.reshape(-1, 3)
        disp_norm = np.linalg.norm(disp_arr, axis=1)
        summary["displacement_final"] = {
            "max_magnitude": float(disp_norm.max()),
            "min_magnitude": float(disp_norm.min()),
        }
        print(f"Final displacement: max={disp_norm.max():.4e} mm")
    except Exception as e:
        print(f"Displacement extraction failed: {e}")

    # Plot energies
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 6))
        if ke_list is not None:
            ax.plot(time_data, ke_list, "b-", label="Kinetic Energy", linewidth=2)
        if ie_list is not None:
            ax.plot(time_data, ie_list, "r-", label="Internal Energy", linewidth=2)
        if ke_list is not None and ie_list is not None:
            te = [k + i for k, i in zip(ke_list, ie_list)]
            ax.plot(time_data, te, "g--", label="Total (KE + IE)", linewidth=1.5, alpha=0.7)

        ax.set_xlabel("Time (ms)")
        ax.set_ylabel("Energy (mJ)")
        ax.set_title("Single Hex Tension — Energy Balance via DPF")
        ax.legend()
        ax.grid(True, alpha=0.3)

        out_png = HERE / "dpf_kinetic_energy.png"
        plt.savefig(out_png, dpi=100, bbox_inches="tight")
        print(f"Saved {out_png}")
        summary["energy_plot"] = str(out_png.name)
    except Exception as e:
        print(f"Energy plot failed: {e}")

    # Geometry visualization with PyVista — deformed mesh with stress contour
    try:
        import pyvista as pv
        import numpy as np
        pv.OFF_SCREEN = True
        mesh = model.metadata.meshed_region

        # Get final displacement and stress
        disp_op = model.results.displacement.on_last_time_freq()
        disp_field = disp_op.eval().get_field(0)

        try:
            stress_op = model.results.stress_von_mises.on_last_time_freq()
            stress_field = stress_op.eval().get_field(0)
            stress_data = np.asarray(stress_field.data).flatten()
            summary["stress_von_mises_final"] = {
                "max": float(stress_data.max()),
                "min": float(stress_data.min()),
            }
            print(f"Final von Mises stress: max={stress_data.max():.4e}")
        except Exception as e:
            print(f"Stress extraction failed: {e}")
            stress_field = None

        # Stress contour on deformed mesh
        plotter_dir = HERE / "dpf_stress_contour.png"
        try:
            from ansys.dpf.core.plotter import DpfPlotter
            pl = DpfPlotter()
            if stress_field is not None:
                pl.add_field(stress_field, mesh, deform_by=disp_field, scale_factor=10.0)
            else:
                pl.add_field(disp_field, mesh)
            pl.show_figure(
                screenshot=str(plotter_dir),
                show_axes=True,
            )
            print(f"Saved {plotter_dir}")
            summary["stress_plot"] = str(plotter_dir.name)
        except Exception as inner:
            print(f"DpfPlotter stress contour failed: {inner}")

        # Deformed wireframe (always works)
        plotter_dir2 = HERE / "dpf_displacement.png"
        mesh.plot(
            deformation=disp_field,
            scale_factor=10.0,
            cpos="iso",
            screenshot=str(plotter_dir2),
            background="white",
            show_edges=True,
            color="lightblue",
        )
        print(f"Saved {plotter_dir2}")
        summary["displacement_plot"] = str(plotter_dir2.name)
    except Exception as e:
        print(f"PyVista plot failed: {e}")

    # Write summary
    summary_path = HERE / "dpf_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSummary saved to {summary_path}")
    print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
