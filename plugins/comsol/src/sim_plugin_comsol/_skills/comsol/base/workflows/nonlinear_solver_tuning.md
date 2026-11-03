# Nonlinear / segregated solver tuning (agentic)

Workflow pattern demonstrated in COMSOL's blog
[Using Agentic Workflows with COMSOL Multiphysics®](https://www.comsol.com/blogs/using-agentic-workflows-with-comsol-multiphysics)
on the **heat sink** CFD tutorial: use a live client–server session (or sim
runtime) to probe segregated-solver settings, run a **small bounded sweep**,
and keep only changes that preserve physical KPIs.

This is **not** a promise that every model will gain ~25% fewer nonlinear
iterations / ~30% runtime (blog-reported example only). Treat those numbers as
an existence proof, not a validation target.

## Preconditions

1. Live model identity known (`ModelUtil.tags()` / `comsol.model.identity`).
2. Baseline solve already converges; capture baseline: wall time, nonlinear /
   segregated iteration counts, and **at least one physical KPI** (e.g. chip
   average temperature via Evaluation Group).
3. Prefer named selections; do not “speed up” by weakening termination into a
   non-physical result.

## Discover editable properties

Do **not** hardcode property names as universal API truth. Prefer:

1. Desktop: right-click the Segregated solver node → **Copy as Code to Clipboard**
   (blog-recommended when the harness is thin).
2. Live probe: `properties()` on the segregated feature (see
   [`../reference/java_api_patterns.md`](../reference/java_api_patterns.md)).
3. Local docs: `sim-comsol-doc search "segregated" --module programming` (or CFD).

Example shape from the blog heat-sink model (tags/`set` keys are
**model-specific**):

```text
model.sol("sol1").feature("s1").feature("se1").set("<prop>", <value>);
```

Blog-listed candidate keys (verify on the live node before sweeping):

`segterm`, `maxsegiter`, `ntolfact`, `segtermonres`, `segreserrfact`,
`segstabacc`, `segcfltech`, `subinitcfl`, `submincfl`, `subforcecfl`,
`subkppid`, `subkipid`, `subkdpid`, `subcfltol`, `subadaptcfltol`,
`segcflaa`, `segcflaacfl`, `segcflaaset`, `segcflaadim`, `segcflaamix`,
`segcflaadelay`, `segcflaafact`, `segcfljtech`, `consistencycheck`, `plot`,
`probesel`.

## Bounded experiment protocol

1. From properties + docs, pick **at most three** promising knobs (CFL /
   stabilization / termination-related — not random).
2. For each knob, try **three values** (nine runs max unless the user asks for
   more).
3. Between runs: restore baseline settings or reload a checkpoint `.mph`.
4. Record per run: setting delta, solve success, time, iteration counts, KPI(s).
5. Accept a candidate only if:
   - solve still converges, and
   - KPI change is within an agreed tolerance (blog: chip temperature must not
     change substantially), and
   - termination is still tolerance-based (or otherwise physically justified).

### Anti-pattern (reject immediately)

Changing termination to “iterations” and setting max iterations to `1` can
collapse iteration counts without a sound solution. Filter these out via KPI
gates.

## Optional UI-dropdown sweeps

Some interface enums (blog: Laminar Flow **compressibility** options) are not
reachable via Parametric Sweep in the UI. An agent can still cycle API values,
re-solve, and compare KPI / time / iterations. Prefer physics justification
over pure speed when choosing the retained option.

## Reporting

Write a short table:

| run | property | value | ok | time | iters | KPI |
|---|---|---|---|---|---|---|

State baseline vs best accepted candidate. Save the winning settings into the
model + a checkpoint `.mph`, and keep the Java/sim snippets under the case
workdir audit tree (`../reference/codex_client_server_loop.md`).

## Related

- Connect loop: [`../reference/codex_client_server_loop.md`](../reference/codex_client_server_loop.md)
- Divergence triage: [`debug_failed_exec.md`](debug_failed_exec.md)
- Checkpoint loop: [`model_review_loop.md`](model_review_loop.md)
