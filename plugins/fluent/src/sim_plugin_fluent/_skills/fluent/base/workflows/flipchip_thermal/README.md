# Flip-Chip BGA Thermal Characterization

Computes JEDEC-style thermal resistances (Theta-JB, Theta-JC) for a flip-chip
package on a 2S2P PCB using conduction-only steady-state analysis in Ansys Fluent.

- Blog post: <https://blog.ozeninc.com/resources/flip-chip-thermal-characterization-using-ansys-fluent>
- Walkthrough video: <https://www.youtube.com/watch?v=xMp4CG80Wq8> (Luis Maldonado, Ozen Engineering)

## Case file

The case is hosted by Ozen Engineering, not vendored in this repo. Use the
`fetch_case.py` helper — stdlib only, idempotent, runs with plain `python3`
or `uv run`:

```bash
uv run fetch_case.py            # downloads to $SIM_DATASETS/flipchip/
uv run fetch_case.py --force    # re-download even if present
uv run fetch_case.py --dest /some/other/dir
```

If `$SIM_DATASETS` is unset, the script downloads to
`~/.cache/sim-datasets/flipchip/` and tells you to export `SIM_DATASETS` to
match. The demo script then looks for the file at
`$SIM_DATASETS/flipchip/Flip_chip_demo_simplified.cas.h5`.

```powershell
$env:SIM_DATASETS = "C:\path\to\datasets"
```

Manual fallback if the Ozen URL breaks: download the zip from the
[Ozen blog post](https://blog.ozeninc.com/resources/flip-chip-thermal-characterization-using-ansys-fluent)
and place `Flip_chip_demo_simplified.cas.h5` under `$SIM_DATASETS/flipchip/`.

- `Flip_chip_demo_simplified.cas.h5` — Fluent 25.1 format, ~40 MB, 455,390 cells, 61 cell zones, 336 wall interfaces
- 2S2P PCB (4 Cu + 3 FR-4 layers), 49 BGA solder balls, die + substrate + underfill + thermal paste
- No fluid zones — pure conduction model

### What the case actually ships with

Don't trust prose descriptions — we verified by re-reading and enumerating every setup node:

| Feature | Shipped state |
|---|---|
| Energy equation | **OFF** |
| Viscous model | k-omega SST (inherited default, irrelevant — no fluid zones) |
| Named expressions | **none** (no pre-wired `Power` or similar) |
| Source terms on all 61 solid zones | `enable: False` (no heat source anywhere) |
| Wall BCs | default adiabatic |
| Materials | **present with full thermal properties** — this is the useful content |

The workflow script has to build every piece of the physics setup on top of a bare-bones geometry + materials case.

### Material thermal properties (k in W/m·K)

| Material | Density (kg/m³) | cp (J/kg·K) | k (W/m·K) | Notes |
|---|---|---|---|---|
| `si-typical` (die) | 2330 | 770 | **180** | silicon die |
| `thermal-paste` | 1900 | 795 | **3.0** | TIM between die and lid |
| `cu-pure` | 8933 | 397 | **387.6** | solid Cu planes |
| `cu-pure-5percent` | 1634 | 1255 | **19.71** | sparse Cu signal layers |
| `fr-4` | 1250 | 1300 | **0.35** | PCB dielectric |
| `substrate` | 1900 | 795 | **orthotropic**: k_xy = 107.2, k_z = 0.552 | package substrate — strong in-plane spreading |
| `underfill` | 1210 | 1172 | **0.8** | between BGA balls |
| `underfill_die` | 1406 | 1148 | **orthotropic**: 1.741 / 1.741 / 2.993 | under die |
| `solder-pb50-sn50` | 8890 | 213 | **46** | BGA balls |

## Method (matching the Ozen video)

The script follows Luis Maldonado's method from the Ozen walkthrough video:

**Common settings:**
- Die power = **5 W** (named expression `power`, source applied as `power/Volume(['flipchip-die-die'])`)
- Reference / ambient temperature = **298.15 K (25°C)**
- Solver: pressure-based, steady, energy on, viscous laminar (no fluid zones)

**Theta-JB — junction-to-board** (as applied from the video, with one measurement-circularity caveat below)
- Interior walls of the flip-chip (die sides, thermal paste sides, substrate sides, underfill sides): adiabatic (heat flux = 0)
- External package surfaces exposed to air (thermal paste top, substrate top, PCB top, PCB sides, PCB bottom): **natural convection, h = 10 W/m²·K, T_∞ = 298.15 K**
- PCB rings (top and bottom, both `*_ring` and `*_inside_ring`): fixed T = 298.15 K
- Measurement:
  - T_j = facet-max on die
  - T_b = ideally the area-average on a "BGA–PCB connection" named selection the video mentions. The simplified case doesn't ship such a named selection, and the closest proxy (`pcb_top_inside_ring`) is itself a fixed-T BC surface in this setup, so measuring there is circular. We use the die–ambient ΔT as a best-effort substitute.

**Theta-JC — junction-to-case**
- Fixed T = 298.15 K on *all* outer walls (Luis's shortcut reuse of the same case file)
- Measurement:
  - T_j = facet-max on die
  - T_c = the fixed 298.15 K on `thermal_paste_top`

## Reference values

| Source | θ_JB (K/W) | θ_JC (K/W) | T_j θ_JB | T_j θ_JC | Notes |
|---|---|---|---|---|---|
| **Ozen blog (published K/W)** | 0.681 | 1.447 | 48.77 °C | 55.22 °C | **unreliable K/W** — see discrepancy note below |
| **Ozen blog (ΔT / 5 W)** | 4.05 | 5.70 | 48.77 °C | 55.22 °C | recomputed from T_j/T_b/T_c the blog lists, using the 5 W power Luis states on camera |
| **This script (5 W, h=10, 2026-04-08)** | **7.75** | **0.585** | 63.76 °C | 27.93 °C | measured against the live simplified case |

### Discrepancy analysis

1. **Ozen blog K/W values are internally inconsistent.** The blog publishes 0.681 and 1.447 K/W, but the absolute temperatures they also print give 4.05 and 5.70 K/W at the 5 W power Luis states on camera. The printed K/W values are wrong; the temperatures are consistent.
2. **Our θ_JB is ~2× higher than the blog-derived target**, most likely because the `cu-pure-5percent` assignment to some PCB layers models sparse copper traces poorly compared to whatever layer stackup the blog's un-simplified case uses.
3. **Our θ_JC is ~10× lower than the blog-derived target.** This is almost certainly because the simplified case omits a heat-spreader lid — our `thermal_paste_top` sits directly on a thin paste layer over the die, giving a very short, low-resistance junction→case path. A production flip-chip has a lid + TIM2 + heatsink stack that adds several K/W.
4. **Physical pattern inversion.** Real flip-chips have θ_JC ≪ θ_JB (short lid path vs long PCB path). Our result matches this pattern. The blog reports θ_JC > θ_JB, which is physically unusual and strongly suggests the blog's BC setup wasn't isolating paths properly.

Don't treat this demo as a reference for any real flip-chip package — it validates the *workflow mechanics*, not the numerical accuracy.

### About the Ozen blog K/W discrepancy

The blog publishes θ_JB = 0.681 K/W and θ_JC = 1.447 K/W but also lists the absolute junction/board/case temperatures. Dividing the temperature deltas by the 5 W die power Luis states on camera gives 4.05 and 5.70 K/W — **roughly 6× and 4× the published K/W numbers**. The *temperatures* the blog lists are internally consistent at 5 W, but the published K/W values are not — most likely an error where ΔT was divided by the wrong power somewhere during the writeup. We regress against the temperature-derived values, not the K/W values the blog prints.

Both characterizations still yield **θ_JC > θ_JB**, which is physically unusual for a real flip-chip (normally θ_JC ≪ θ_JB because the junction→case path is shorter and lower-k than the junction→board path). This likely reflects the "simplified" nature of the case geometry — for example the model probably lacks a heat-spreader lid, or uses coarser substrate Cu coverage than a production package. Don't use this demo's numbers as representative of any real flip-chip.

### A wall-of-numbers tangent: mechanics gotcha for extraction

`solver.fields.reduction.maximum()` fails on this case with
`api-checks-before-command-or-query … Error Object: setup/named-expressions/temp_expr_1/get-value` —
pyfluent creates an internal temporary named expression and can't re-evaluate it.
**Workaround:** use `solver.settings.solution.report_definitions.surface[...]` with
`compute(report_defs=[...])`, which returns `[{'name': [value, 'unit']}, ...]`.

## Run

```
sim run workflows/flipchip_thermal/demo_flipchip_thermal.py --solver=fluent --json
```

The script is a **reference script only** — it calls `pyfluent.launch_fluent()` directly.
For the `sim exec`-friendly step-by-step snippets that work against a live `sim connect` session,
see `tmp/step{4,4b,5,6,6b,6c,7,7b,8,8b}_*.py` in the `sim-proj` repo.

## Skill migration path

This workflow script validates the setup on win1. Once proven, the patterns
(conduction-only thermal, BC switching, theta extraction via report_definitions,
natural-convection BC application) feed into a "thermal characterization" task
template in `skills/fluent-sim/SKILL.md`.
