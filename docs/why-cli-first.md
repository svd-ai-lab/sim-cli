# Why CLI-first?

Engineering simulation is file-based, scriptable, local, artifact-heavy, and
long-running. CAE agents work with solver executables, model files,
Python/Java/journal scripts, shell commands, logs, checkpoints, and plots — a
CLI command surface composes with all of that and matches how Codex CLI, Claude
Code, and other coding agents already operate.

MCP is useful for API-style integrations and remote tool discovery, but a broad
MCP surface adds context overhead and wrapper maintenance. For COMSOL, Abaqus,
Ansys Workbench, OpenFOAM, LTspice, and similar solvers, sim-cli keeps the
source of truth as a small, auditable command loop.

The practical consequence: an agent learns the whole surface from one
`sim --json describe` call, and every command it runs is a line a human can
re-run, paste into a bug report, or drop into a shell script. See
[agent-readability.md](agent-readability.md) for the I/O contract that makes
this work.
