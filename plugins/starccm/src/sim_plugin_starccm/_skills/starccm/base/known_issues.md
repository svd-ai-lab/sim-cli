# Known Issues — Star-CCM+

## 1. License file must be configured

**Symptom**: Exit code 8, "Unable to find a path to any license file or license server"

**Cause**: `CDLMD_LICENSE_FILE` environment variable not set.

**Fix**: The driver auto-detects `license.dat` near the installation. If not found, set manually:
```bash
set CDLMD_LICENSE_FILE=E:\Program Files (x86)\Siemens\license.dat
```

## 2. CJK encoding on Chinese Windows

**Symptom**: `UnicodeDecodeError: 'gbk' codec can't decode byte` when running macros.

**Cause**: Star-CCM+ outputs Chinese characters in its status messages on Chinese Windows. Python's default subprocess text mode uses the system locale (GBK).

**Fix**: Driver uses bytes mode + UTF-8 decode with replace. Already handled in `driver.py`.

## 3. Java compilation errors in macros

**Symptom**: Exit code 1, error messages like "找不到符号" (symbol not found).

**Cause**: The macro uses Java API methods that don't exist in the installed version. Star-CCM+ compiles Java macros at runtime.

**Fix**: Use the macro recorder to discover correct API calls for your version. The API changes between major versions.

## 4. ~15-20 second startup overhead per run

**Symptom**: Even trivial macros take 15+ seconds.

**Cause**: JVM startup + license checkout + server initialization.

**Mitigation**: Design macros to do meaningful work per invocation. Combine multiple steps into single macros rather than running many small ones.

## 5. `getVersion()` does not exist on Simulation

**Symptom**: Compilation error when calling `sim.getVersion()`.

**Fix**: Use `sim.getPresentationName()` for identification. Version is reported in stdout by Star-CCM+ at startup.

## 6. SimpleCylinderPart creates only 1 boundary by default

**Symptom**: Region from `SimpleCylinderPart` has only 1 boundary (the whole surface) instead of separate inlet/outlet/wall.

**Cause**: `OneRegionPerPart` + `OneBoundaryPerPartSurface` treats the entire cylinder surface as one boundary. The cylinder primitive does not have separate named surfaces for ends vs. lateral wall.

**Fix**: After region creation, split boundaries manually or use CAD import with named faces.

## 7. SimpleBlockPart/SimpleCylinderPart only create 1 PartSurface — cannot set inlet/outlet

**Symptom**: `newRegionsFromParts` with `OneBoundaryPerPartSurface` creates only 1 boundary for the entire geometry. Cannot assign different BC types to different faces.

**Cause**: Simple primitive parts (block, cylinder, sphere) are single-surface geometry objects. The 3D-CAD API (`createBox`, `createSketch3D`, `createExtrusionMerge`) does not exist in this version (21.02).

**Workaround options**:
1. **GUI macro recorder**: Create geometry in GUI, record the macro, replay in batch
2. **Import external CAD/mesh**: Import .stl/.step/.ccm files that have named surfaces
3. **Body force driven flow**: Use single-wall boundary + momentum source term (limited physics)

**Impact**: Cannot do inlet/outlet CFD from pure batch Java macros without pre-existing geometry or recorded macro.

## 8. Class name must match file name

**Symptom**: Compilation error or class not found.

**Cause**: Java requires the public class name to match the file name (without `.java` extension).

**Fix**: Ensure `public class MyMacro` is in a file named `MyMacro.java`, or use a file name that matches: `starccm_smoke_test.java` → `public class starccm_smoke_test`.
