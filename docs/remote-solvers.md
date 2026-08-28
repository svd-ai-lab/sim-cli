# Remote solvers

Most work happens on one machine, where `sim connect` starts a local runtime for
you and no `--host` is needed. This document covers the other case: the solver
lives on a workstation, lab box, or HPC login node, and the agent runs somewhere
else.

## Setup

Install `sim-cli-core` and the solver plugin **on the solver host**, then start
the server there:

```bash
# On the solver host.
uv run sim serve --host 0.0.0.0 --port 7600
```

Point the agent machine at it. `--host`, `--port`, and `--session` are
group-level flags, so they precede the subcommand:

```bash
# On the agent machine.
uv run sim --host <solver-host-ip> check <solver>
uv run sim --host <solver-host-ip> connect --solver <solver>
uv run sim --host <solver-host-ip> inspect session.summary
uv run sim --host <solver-host-ip> disconnect
```

`SIM_HOST` and `SIM_PORT` set the same values through the environment.

## Security

**Only bind `sim serve` to a trusted network** such as a VPN, Tailscale, or a
protected LAN. Never expose it to the public internet.

The runtime has no authentication layer. `POST /connect` and `POST /exec` run
code on the solver host, so anyone who can reach the port can execute arbitrary
code as the user running `sim serve`.

Note the asymmetry in what is currently gated: `POST /shutdown` is
localhost-only (`server.py`), so a network peer cannot stop the server — but the
endpoints that execute code are not restricted the same way. Treat network
reachability itself as the security boundary.

## Caveats

`sim serve --reload` drops all sessions on any source change under the watched
tree, which matters more on a shared solver host than locally. Launch without
`--reload` for long-running work.
