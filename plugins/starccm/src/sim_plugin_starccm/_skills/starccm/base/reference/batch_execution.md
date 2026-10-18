# Star-CCM+ Batch Execution Reference

## Command-line syntax

```bash
starccm+ -batch macro.java [options] [case.sim]
```

## Key flags

| Flag | Purpose | Example |
|------|---------|---------|
| `-batch macro.java` | Run macro in batch mode (no GUI) | Required |
| `-np N` | Number of parallel processors | `-np 8` |
| `-server` | Start in server mode | For client connections |
| `-port N` | Server port | `-port 48000` |
| `-noexit` | Keep running after macro completes | For server mode |
| `-power` | Use power-on-demand licensing | For cloud/HPC |
| `-rsh "ssh ..."` | Remote shell for MPI | Cluster runs |
| `-machinefile file` | Node list for distributed | Cluster runs |

## License configuration

Star-CCM+ requires the `CDLMD_LICENSE_FILE` environment variable:

```bash
# Point to local license file
set CDLMD_LICENSE_FILE=E:\Program Files (x86)\Siemens\license.dat

# Or point to license server
set CDLMD_LICENSE_FILE=1999@license-server.company.com
```

The sim driver auto-detects `license.dat` near the installation directory.

## Execution examples

```bash
# Simple batch run
starccm+ -batch solve.java myCase.sim

# Parallel batch (8 cores)
starccm+ -batch solve.java -np 8 myCase.sim

# Batch without a .sim file (macro creates its own simulation)
starccm+ -batch smoke_test.java
```

## sim-cli integration

```bash
# Run via sim (auto-detects starccm+ path and license)
sim run macro.java --solver starccm

# Check installation
sim check starccm

# Lint macro before running
sim lint macro.java
```

## Timing expectations

| Operation | Typical duration |
|-----------|-----------------|
| Startup (JVM + license) | 15-20s |
| Simple macro (no solve) | 15-25s total |
| Mesh generation | 30s-5min (depends on size) |
| CFD solve (1000 iterations) | 1-30min (depends on mesh) |

Plan macros to do meaningful work per invocation to amortize startup cost.
