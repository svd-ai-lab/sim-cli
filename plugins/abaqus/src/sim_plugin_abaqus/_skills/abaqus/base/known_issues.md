# Known Issues — Abaqus Driver

## Coarse mesh stiffness

**Discovered**: 2026-04-13
**Status**: Expected behavior (not a bug)
**Description**: The 4-element CPS4 cantilever beam E2E test gives tip
deflection of ~5.75e-6 m vs analytical ~2e-5 m. This is expected for a
coarse linear quad mesh — FEM solutions are stiffer than analytical when
under-meshed. Refining to 40 elements gives ~1.9e-5 m (within 5% of
analytical).
**Impact**: Physics acceptance range must be wide enough to accommodate
mesh density variations.

## CJK locale file paths

**Discovered**: 2026-04-13
**Status**: Workaround documented
**Description**: On Chinese/Japanese/Korean Windows, Abaqus may have
issues with non-ASCII characters in job directory paths. The `.dat`
output file header shows garbled date strings (e.g., "4月" renders as
"4��").
**Workaround**: Use ASCII-only paths for Abaqus working directories.
Result parsing uses `errors="replace"` to handle encoding issues.

## Output file cleanup

**Discovered**: 2026-04-13
**Status**: By design
**Description**: Abaqus creates multiple output files per job (.dat, .odb,
.msg, .sta, .com, .prt, .sim, .simdir). When running via `sim run` with
`.inp` files, these are created in the input file's directory.
**Workaround**: The E2E test script uses `tempfile.TemporaryDirectory`
to isolate output files. For production use, consider dedicated working
directories.
