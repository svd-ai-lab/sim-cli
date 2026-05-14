# Java batch patterns — `comsolcompile` + `comsolbatch`

Use this reference when the task is **write a `.java` file → compile with
`comsolcompile.exe` → run with `comsolbatch.exe`**. This is COMSOL's own
one-shot Java execution path — a first-class execution mode, not a fallback.
Prefer it for settled deterministic recipes and reproducible/CI/fan-out runs
(see the decision table in `SKILL.md`). It is different from the JPype runtime
path in `java_api_patterns.md`, which targets a live Python-driven session for
stateful building and introspection.

## Skeleton

```java
import com.comsol.model.*;
import com.comsol.model.util.*;

public class MyModel {
  public static Model run() throws Exception {
    Model model = ModelUtil.create("Model1");

    model.component().create("comp1", true);
    model.component("comp1").geom().create("geom1", 3);
    // ... geometry / materials / physics / mesh / study ...
    model.sol("sol1").runAll();

    // Print KPIs as `key=value` lines to stdout for the agent to extract:
    System.out.println("T_max_K=" + tmax);
    return model;
  }

  public static void main(String[] args) throws Exception { run(); }
}
```

## The ONE rule that breaks every novice attempt

> **Use chain-style: `model.X("tag").Y("tag2")....`**
> **DO NOT declare typed variables for COMSOL nodes.**

There is no public `Component`, `Geometry`, `Physics`, `HeatTransfer`,
`Material`, `Interval`, `TemperatureBoundary`, etc. type in the COMSOL
Java API. Every child node looks like a `ModelEntity` to the compiler,
but its useful shape comes from the **container** that returned it.

### Correct (chain style)

```java
model.component().create("comp1", true);
model.component("comp1").geom().create("geom1", 1);
model.component("comp1").geom("geom1").create("i1", "Interval");
model.component("comp1").geom("geom1").feature("i1").set("p2", 0.1);
model.component("comp1").geom("geom1").run();

model.component("comp1").physics().create("ht", "HeatTransfer", "geom1");
model.component("comp1").physics("ht").create("temp1", "TemperatureBoundary", 0);
model.component("comp1").physics("ht").feature("temp1").selection().set(new int[]{1});
model.component("comp1").physics("ht").feature("temp1").set("T0", "1000[K]");
```

### Wrong (`comsolcompile` rejects with `cannot be resolved to a type`)

```java
// ❌ DO NOT WRITE THIS
Component comp = model.component().create("comp1", true);
Geometry geom = comp.geom().create("geom1", 1);
Interval interval = geom.create("int1", "Interval");
HeatTransfer ht = comp.physics().create("ht", "HeatTransfer", "geom1");
TemperatureBoundary tempBC = ht.create("temp1", "TemperatureBoundary", 0);
```

If you see `cannot be resolved to a type` errors from `comsolcompile`,
**the fix is always to delete the typed declarations** and walk through
`model.X("tag")...` from scratch. **It is not a classpath problem.**
Do not waste turns inspecting JAR contents.

## Calling pattern reminders

- **Selections by entity dim**: `selection().set(new int[]{...})` is for the
  **integer entity indices on the geometry's selection list**, where
  the dimension was set by the third arg to `physics(...).create(name, type, dim)`:
  `0` = point, `1` = edge, `2` = face, `3` = domain. Picking the wrong
  dim means COMSOL silently won't apply the BC.
- **Selection by name**: `.selection().named("geom1_sel1")`
  or `.selection().all()` if the BC is global.
- **Property values are strings** with units: `set("T0", "1000[K]")`.
  Bare numbers usually work too but explicit units are safer.
- **Tags vs names**: `.create("temp1", ...)` makes a node tagged `temp1`;
  `.label("Inlet")` sets a display label. Refer to it later by tag, not label.
- **Source-property for material+temperature ambient values**: most
  features have a `<prop>_src` switch alongside `<prop>` itself:
  ```java
  feat.set("epsilon_rad_mat", "userdef");  // tell COMSOL to use userdef
  feat.set("epsilon_rad", "0.98");          // not the material's value
  feat.set("Tamb_src", "userdef");
  feat.set("Tamb", "300[K]");
  ```
  Forgetting the `_src` toggle is the classic
  `Undefined material property` runtime error.

## Solver pattern

```java
model.study().create("std1");
model.study("std1").create("stat", "Stationary");
model.study("std1").feature("stat").set("activate", new String[]{"ht", "on"});

model.sol().create("sol1");
model.sol("sol1").study("std1");
model.sol("sol1").create("st1", "StudyStep");
model.sol("sol1").feature("st1").set("study", "std1");
model.sol("sol1").feature("st1").set("studystep", "stat");
model.sol("sol1").create("v1", "Variables");
model.sol("sol1").create("s1", "Stationary");
model.sol("sol1").runAll();
```

Or, for simple Stationary studies, let createAutoSequences do it:

```java
model.study("std1").createAutoSequences("all");
model.sol("sol1").runAll();
```

## KPI extraction inside the same JVM

`comsolbatch` runs your class in a sandbox that **blocks `java.io.FileWriter`**
(security manager). Always print KPIs to stdout, then redirect to a log
file from the shell:

```bash
comsolbatch.exe -inputfile MyModel.class -nosave > comsol.log 2>&1
```

In Java:

```java
double tmax = model.result().numerical().create("max1", "MaxLine")
    .set("data", "dset1").selection().all()  // chain across container changes
    , 0;  // placeholder — real pattern below

// Cleaner:
model.result().numerical().create("max1", "MaxLine");
model.result().numerical("max1").set("data", "dset1");
model.result().numerical("max1").selection().all();
model.result().numerical("max1").setIndex("expr", "T", 0);
model.result().numerical("max1").setIndex("unit", "K", 0);
double tmax = model.result().numerical("max1").getReal()[0][0];
System.out.println("T_max_K=" + tmax);
```

## "Solve failed" / `Undefined ...` triage

| Error | Likely cause | Fix |
|---|---|---|
| `cannot be resolved to a type` at compile | typed Java vars (`Component comp = ...`) | rewrite chain-style |
| `Undefined material property "X"` at solve | feature uses material value but `<X>_src` not set to userdef | set `<X>_src` to `userdef` then `<X>` to actual value |
| `Source_selection_not_meshed` | selection is empty or on wrong dim | check `.selection()` index list against `geom("geom1").feature("...").box(...)` first |
| `Failed to solve linear system` | bad mesh / under-constrained physics | check BC count == DoF count |

When `comsolcompile` exits non-zero, the first 3 lines of its stderr name
the line and column. Read those — the underlying issue is almost always
in **your** `.java`, not in the compiler classpath.
