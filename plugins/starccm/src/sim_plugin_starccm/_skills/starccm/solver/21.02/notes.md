# Star-CCM+ 2602 (21.02) — Version Notes

## Version info
- **Product**: Simcenter STAR-CCM+ 2602-R8
- **Build**: 21.02.007 (win64/clang20.1vc14.2-r8)
- **Release date**: Feb 2026
- **License version required**: 2026.02 or greater

## API notes
- `Simulation.getPresentationName()` — works, returns simulation title
- `Simulation.getVersion()` — does NOT exist in this version
- Java macros compiled at runtime with the bundled JDK
- Embedded Python 3.x available via `ccmpython3.bat` (infrastructure only, not simulation API)

## Known quirks
- Chinese Windows: stdout contains CJK characters in status messages
- Startup includes automatic local server creation on port 47827
- License checkout message: "1 copy of ccmpsuite checked out"
