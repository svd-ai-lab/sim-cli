# Version awareness — the Step-0 probe

**Mandatory.** The first thing every task does after the session starts
is probe the runtime version and use the result to pick the right
subfolder inside the driver skill.

---

## Why this exists

A snippet written for one SDK or solver release can silently fail on
another release, or worse, appear to run while using the wrong API
surface. Without an explicit version check, the agent has to guess from
package versions and local paths — exactly the failure mode this probe
eliminates.

---

## The probe

After `sim connect` succeeds (persistent) — or at the start of a
one-shot task, against a short-lived session:

```bash
sim --host <host> inspect session.versions
```

Returns:

```json
{
  "sdk":                 {"name": "example-sdk", "version": "1.2.3"},
  "solver":              {"name": "example",     "version": "4.5"},
  "profile":             "example_sdk_1_2",
  "active_sdk_layer":    "sdk-1.2",
  "active_solver_layer": "solver-4.5",
  "env_path":            "/.../.sim/envs/example-sdk-1-2"
}
```

---

## How to use the result

The driver skill's `SKILL.md` tells you it has a layered folder
structure:

```
<driver>/
  base/                ← always relevant
  sdk/<slug>/          ← SDK-specific deltas (empty for SDK-less drivers)
  solver/<slug>/       ← solver-release deltas
```

Use the probe's fields to pick the right `<slug>`:

- **`base/`** — always load.
- **`sdk/<active_sdk_layer>/`** — load if set.
- **`solver/<active_solver_layer>/`** — load if set.

Later layers override earlier ones on identically-named files.

Example:

```
active_sdk_layer = "sdk-1.2"     → read sdk/sdk-1.2/
active_solver_layer = "solver-4.5" → read solver/solver-4.5/
```

If a driver skill has snippets in both `base/snippets/` and
`sdk/<slug>/snippets/`, prefer the SDK-layer snippet when it exists for
the same task — it was written against the exact API surface you're
connected to.

---

## Failure modes — stop and surface

Do **not** proceed silently if any of these hold:

- `profile` is empty or missing.
- `profile` is not listed in the driver's `compatibility.yaml`.
- `profile` is marked `deprecated` in the driver's `compatibility.yaml`.
- `active_sdk_layer` points to a directory that does not exist in the
  driver skill.

**Action**: stop, print the full `session.versions` payload, ask the
user how to proceed (upgrade, downgrade, skip).

Full contract: [`sim-cli/docs/architecture/version-compat.md`](https://github.com/svd-ai-lab/sim-cli/blob/main/docs/architecture/version-compat.md).

---

## Notes for SDK-less drivers

Some drivers have no Python SDK and drive tools through batch
executables or other local interfaces. For these, `active_sdk_layer` is
typically `null` and only `active_solver_layer` matters. The probe shape
is the same; just ignore the null fields.
