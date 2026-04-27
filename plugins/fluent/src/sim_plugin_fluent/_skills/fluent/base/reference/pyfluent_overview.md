# PyFluent Reference Docs

Versioned snapshots of PyFluent API documentation. Used by the agent skill for fast lookup.

**Live docs:** https://fluent.docs.pyansys.com/version/stable/index.html

When docs disagree with the live session, trust the session. Use `sim exec "print(dir(...))"` to introspect.

## Versions

| Version | Status | Fluent compatibility |
|---|---|---|
| [0.38](0.38/) | Current | Fluent 2025 R2 (v252) |

## Adding a new version

1. Copy the current version folder: `cp -r 0.38 0.39`
2. Update changed API paths
3. Run integration tests to verify
4. See `driver-upgrade` skill for the full process
