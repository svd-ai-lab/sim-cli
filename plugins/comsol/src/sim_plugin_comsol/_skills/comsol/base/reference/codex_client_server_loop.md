# Codex / bare Java client–server loop

Aligns this skill with COMSOL's public agentic-workflow guidance:
[Using Agentic Workflows with COMSOL Multiphysics®](https://www.comsol.com/blogs/using-agentic-workflows-with-comsol-multiphysics)
(2026-09-18). Prefer the **sim runtime** (`uv run sim connect …`) when it is
installed. Use this **bare Java** path when Codex (or another agent) only has
shell + a licensed COMSOL install, or when you need a minimal blog-style
wrapper with no Python plugin.

Do **not** confuse `comsolmphserver` (Multiphysics computational server) with
**COMSOL Server™** (app-deployment product).

## When to use which path

| Goal | Prefer |
|---|---|
| Structured inspect / checkpoint / shared Desktop | `uv run sim connect --solver comsol …` |
| Already-running server + Desktop; attach only | `attach_only=true` + `port=<n>` (see `SKILL.md`) |
| Blog-minimal Codex skill: compile Java, connect, mutate, disconnect | This document |
| Settled one-shot recipe | `comsolcompile` + `comsolbatch` (`java_batch_patterns.md`) |

## Interactive loop (official shape)

1. Start `comsolmphserver` (or reuse one that is already up).
2. Connect COMSOL Desktop as client; load the target model (engineer-in-the-loop).
3. Agent generates a small `.java` program that uses the COMSOL API for Java.
4. Compile with COMSOL's `comsolcompile`, run with COMSOL's bundled JRE and
   `plugins/*` on the classpath.
5. Program: **connect → read model tag(s) → controlled change / study → disconnect**.
6. Persist the `.java`, program stdout/stderr, and COMSOL progress log for audit.
7. Reason over output; plan the next bounded step.

Smoke test used in the COMSOL blog: **set a global parameter, then read it
back** (and confirm it appears in the Desktop UI).

## Discover install + port

Windows defaults (adjust if the user installed elsewhere):

```text
COMSOLROOT=C:\Program Files\COMSOL\COMSOL64\Multiphysics
  or D:\Program Files\COMSOL\COMSOL64\Multiphysics
BIN=%COMSOLROOT%\bin\win64
JAVA=%COMSOLROOT%\java\win64\jre\bin\java.exe
```

Start server (if none is running):

```powershell
& "$env:COMSOLROOT\bin\win64\comsolmphserver.exe"
```

Read the **port** from the server console (example: `49673`). Same-machine
client+server works with any license type; cross-machine needs FNL
(COMSOL docs / KB 1299).

## Minimal connect–mutate–disconnect Java

Save as `BlogPing.java` in a workspace folder. Always list tags **before**
mutating; never assume `model1` is the user's target.

```java
import com.comsol.model.*;
import com.comsol.model.util.*;

public class BlogPing {
  public static void main(String[] args) {
    String host = args.length > 0 ? args[0] : "localhost";
    int port = args.length > 1 ? Integer.parseInt(args[1]) : 2036;
    String preferTag = args.length > 2 ? args[2] : null;
    try {
      System.out.println("CONNECT host=" + host + " port=" + port);
      ModelUtil.connect(host, port);
      String[] tags = ModelUtil.tags();
      System.out.println("TAGS_COUNT=" + (tags == null ? -1 : tags.length));
      if (tags != null) {
        for (String t : tags) System.out.println("TAG=" + t);
      }
      if (tags == null || tags.length == 0) {
        throw new IllegalStateException("no models on server");
      }
      String tag = preferTag != null ? preferTag : tags[0];
      Model m = ModelUtil.model(tag);
      System.out.println("ACTIVE_TAG=" + tag);
      m.param().set("codex_blog_ping", "42");
      System.out.println("PARAM_GET=" + m.param().get("codex_blog_ping"));
      ModelUtil.disconnect();
      System.out.println("DISCONNECT_OK");
    } catch (Throwable e) {
      System.out.println("FAIL " + e.getClass().getName() + ": " + e.getMessage());
      e.printStackTrace(System.out);
      try { ModelUtil.disconnect(); } catch (Throwable ignore) {}
      System.exit(1);
    }
  }
}
```

Compile and run (PowerShell):

```powershell
$COMSOLROOT = "D:\Program Files\COMSOL\COMSOL64\Multiphysics"  # edit
$BIN = Join-Path $COMSOLROOT "bin\win64"
$JAVA = Join-Path $COMSOLROOT "java\win64\jre\bin\java.exe"
Set-Location $workdir
& "$BIN\comsolcompile.exe" "BlogPing.java"
& $JAVA -cp "$workdir;$COMSOLROOT\plugins\*" BlogPing localhost <port> [<modelTag>]
```

Evidence of success: `CONNECT` / `TAGS_COUNT` / `PARAM_GET=42` / `DISCONNECT_OK`
in the program log, and the parameter visible in Desktop if that model is open.

## Artifact layout (blog + this skill)

For each agent step against the server, keep:

```text
<case-workdir>/
  java/<step>_*.java
  logs/<step>_java.stdout.txt
  logs/<step>_java.stderr.txt
  logs/<step>_comsol_progress.txt   # if available
  checkpoints/<optional>.mph
```

## Codex skill packaging note

The COMSOL blog's example Codex skill name is `comsol-api` (lightweight
wrapper only). **This plugin skill (`comsol-sim`) supersedes that minimal
skill** when `sim-plugin-comsol` is installed: use `sim connect` / `sim exec` /
`sim inspect` first, and fall back to the bare Java loop above when sim-cli is
absent. Do not install a second conflicting `comsol-api` skill that bypasses
checkpoints unless the user explicitly wants the blog-minimal harness.

## Related references

- Live probing: [`java_api_patterns.md`](java_api_patterns.md)
- Batch recipes: [`java_batch_patterns.md`](java_batch_patterns.md)
- Solver tuning demo workflow: [`../workflows/nonlinear_solver_tuning.md`](../workflows/nonlinear_solver_tuning.md)
- Official API overview: https://www.comsol.com/support/learning-center/article/overview-of-the-comsol-api-107912
- Client–server docs (6.4): https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_running.38.19.html
