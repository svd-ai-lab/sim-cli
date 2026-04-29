"""Loader for per-driver `compatibility.yaml` files.

Each driver ships a `compatibility.yaml` next to its `driver.py`. This
module parses that file into a small typed surface (`Profile`,
`Compatibility`) and answers three questions:

  1. Given a detected solver version, which profile applies?
  2. What profiles does sim-cli know about across all drivers?
  3. For a given profile, which sim-skills overlay layers are active?

It is intentionally a **metadata catalogue**, not a runtime. sim-cli
runs every driver in its own process — compat.yaml exists so the CLI
can tell users which profile applies to a detected solver version and
so the skills layer can resolve a profile to its (sdk, solver)
overlay paths.

## Plugin awareness

Driver registry entries point at packages (built-in
``sim.drivers.<name>`` or external ``sim_plugin_<name>``). For both,
``compatibility.yaml`` lives at the package root and is loaded via
``importlib.resources`` so wheel-installed plugins work the same as
in-tree built-ins. ``load_compatibility_by_name(name)`` is the
plugin-aware entry point; ``load_compatibility(driver_dir)`` remains
for path-based callers and tests.

Public surface:
    load_compatibility_by_name(name)            -> Compatibility | None
    load_compatibility(driver_dir)              -> Compatibility   (legacy, path-based)
    Compatibility.resolve(solver_version)       -> Profile | None
    Compatibility.profile_by_name(name)         -> Profile | None
    find_profile(name)                          -> (driver, Profile) | None
    all_known_profiles()                        -> list[(driver, Profile)]
    safe_detect_installed(driver)               -> list

Skills layering surface:
    find_skills_root()                          -> Path | None
    verify_skills_layout(root, profiles=None)   -> list[str]
    skills_block_for_profile(driver, profile)   -> dict
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources as _resources
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class Profile:
    """A named (SDK pin, solver version list) tuple from compatibility.yaml.

    `sdk` is optional: solvers like OpenFOAM have no Python SDK to pin.

    `active_sdk_layer` and `active_solver_layer` declare which sub-folders
    under `<sim-skills>/<driver>/sdk/` and `<sim-skills>/<driver>/solver/`
    apply to this profile. Both are optional — SDK-less drivers leave
    `active_sdk_layer` unset, drivers with no version-sensitive solver
    content leave `active_solver_layer` unset. The `base/` overlay is
    always active and needs no field.
    """
    name: str
    solver_versions: tuple[str, ...]
    sdk: str | None = None
    notes: str = ""
    active_sdk_layer: str | None = None
    active_solver_layer: str | None = None

    def matches_solver(self, solver_version: str) -> bool:
        return _normalize_solver_version(solver_version) in self.solver_versions

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "sdk": self.sdk,
            "solver_versions": list(self.solver_versions),
            "notes": self.notes.strip(),
            "active_sdk_layer": self.active_sdk_layer,
            "active_solver_layer": self.active_solver_layer,
        }


@dataclass(frozen=True)
class Compatibility:
    """Parsed compatibility.yaml for one driver."""
    driver: str
    profiles: tuple[Profile, ...]
    sdk_package: str | None = None

    def profile_by_name(self, name: str) -> Profile | None:
        for p in self.profiles:
            if p.name == name:
                return p
        return None

    def resolve(self, solver_version: str) -> Profile | None:
        """Return the first profile whose solver_versions contains V.

        Profiles are walked in declaration order; if multiple match, the
        first wins. Returns None when no profile matches.
        """
        normalized = _normalize_solver_version(solver_version)
        for p in self.profiles:
            if normalized in p.solver_versions:
                return p
        return None


def _normalize_solver_version(v: str) -> str:
    """Coerce solver version strings into the canonical short form ('25.2').

    Handles common variants:
      "25.2"     -> "25.2"
      "25.2.0"   -> "25.2"
      "2025 R2"  -> "25.2"
      "v252"     -> "25.2"
      "252"      -> "25.2"
    """
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""

    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 3 and ("v" + digits in s.lower() or s == digits):
        return f"{digits[:2]}.{digits[2]}"

    s_compact = s.replace(" ", "").lower()
    if "r" in s_compact:
        year_part, _, rel_part = s_compact.partition("r")
        if year_part.isdigit() and rel_part.isdigit() and len(year_part) == 4:
            return f"{year_part[2:]}.{rel_part}"

    parts = s.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}"

    return s


def _registry_module_for(driver_name: str) -> str | None:
    """Resolve a driver name to its package module path via the registry.

    Returns the *module path* (e.g. ``"sim.drivers.coolprop"`` for built-ins
    or ``"sim_plugin_coolprop"`` for external plugins). Returns None when
    the driver isn't registered.

    We import the registry lazily to avoid a circular import at module load
    time — ``sim.drivers`` imports from ``sim.driver`` which imports from
    nowhere; ``sim.compat`` is the higher layer.
    """
    from sim.drivers import _REGISTRY  # local import — see docstring
    for name, spec in _REGISTRY:
        if name == driver_name:
            module_path, _, _cls = spec.rpartition(":")
            return module_path or None
    return None


def load_compatibility_by_name(driver_name: str) -> "Compatibility | None":
    """Plugin-aware ``compatibility.yaml`` loader.

    Resolves ``driver_name`` to its package via the registry, then reads
    ``compatibility.yaml`` from the package using ``importlib.resources``.
    Works identically for built-in drivers (``sim.drivers.<name>``) and
    external plugins (``sim_plugin_<name>``).

    Returns None when:
      * the driver isn't registered, OR
      * its package has no ``compatibility.yaml`` (some drivers are
        SDK-less / version-insensitive — e.g. simpy), OR
      * the file is malformed (logged at WARNING in the future; silent
        for now to match legacy behaviour).
    """
    module_path = _registry_module_for(driver_name)
    if module_path is None:
        return None
    try:
        traversable = _resources.files(module_path).joinpath("compatibility.yaml")
        if not traversable.is_file():
            return None
        text = traversable.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None
    return _parse_compatibility_text(driver_name, text)


def find_profile(profile_name: str) -> tuple[str, "Profile"] | None:
    """Find a profile by name across every registered driver."""
    from sim.drivers import _REGISTRY  # local import — see _registry_module_for
    for driver_name, _spec in _REGISTRY:
        compat = load_compatibility_by_name(driver_name)
        if compat is None:
            continue
        prof = compat.profile_by_name(profile_name)
        if prof is not None:
            return compat.driver, prof
    return None


def all_known_profiles() -> list[tuple[str, "Profile"]]:
    """Enumerate every profile across every registered driver."""
    from sim.drivers import _REGISTRY  # local import — see _registry_module_for
    out: list[tuple[str, Profile]] = []
    for driver_name, _spec in _REGISTRY:
        compat = load_compatibility_by_name(driver_name)
        if compat is None:
            continue
        for p in compat.profiles:
            out.append((compat.driver, p))
    return out


def safe_detect_installed(driver) -> list:
    """Call driver.detect_installed() defensively."""
    method = getattr(driver, "detect_installed", None)
    if method is None:
        return []
    try:
        result = method()
        return list(result) if result else []
    except Exception:
        return []


def _parse_compatibility_text(source_label: str, text: str) -> Compatibility:
    """Parse a compatibility.yaml string into a Compatibility object.

    ``source_label`` is used only in error messages (path, package, etc.).
    Raises ``ValueError`` on malformed input. Trusts well-formed input; the
    caller decides whether a missing file is an error.
    """
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{source_label} top-level must be a mapping")

    try:
        driver = raw["driver"]
        raw_profiles = raw.get("profiles") or []
    except KeyError as e:
        raise ValueError(f"{source_label} missing required field: {e}") from e

    sdk_package = raw.get("sdk_package")

    profiles: list[Profile] = []
    for i, p in enumerate(raw_profiles):
        if not isinstance(p, dict):
            raise ValueError(f"{source_label} profile #{i} must be a mapping, not {type(p).__name__}")
        try:
            profiles.append(
                Profile(
                    name=p["name"],
                    sdk=p.get("sdk"),
                    solver_versions=tuple(
                        _normalize_solver_version(v) for v in p["solver_versions"]
                    ),
                    notes=p.get("notes", "") or "",
                    active_sdk_layer=p.get("active_sdk_layer"),
                    active_solver_layer=p.get("active_solver_layer"),
                )
            )
        except KeyError as e:
            raise ValueError(
                f"{source_label} profile #{i} missing required field: {e}"
            ) from e

    return Compatibility(
        driver=driver,
        sdk_package=sdk_package,
        profiles=tuple(profiles),
    )


@lru_cache(maxsize=64)
def load_compatibility(driver_dir: str | Path) -> Compatibility:
    """Load and cache the compatibility.yaml for one driver directory.

    Path-based loader retained for tests and any caller that already has
    the directory in hand. Plugin-aware code should call
    ``load_compatibility_by_name(driver_name)`` instead — that one resolves
    via the registry and reads from the package's resources, which works
    for wheel-installed plugins.
    """
    path = Path(driver_dir) / "compatibility.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"compatibility.yaml not found for driver at {driver_dir}"
        )
    return _parse_compatibility_text(str(path), path.read_text(encoding="utf-8"))


# ── Skills layering ─────────────────────────────────────────────────────────


_SKILLS_HINT = (
    "set SIM_SKILLS_ROOT or place sim-skills/ next to sim-cli/"
)


def find_skills_root() -> Path | None:
    """Locate the sim-skills root.

    Probe order:
      1. ``SIM_SKILLS_ROOT`` env var (authoritative when set)
      2. ``../sim-skills`` sibling of the sim-cli checkout

    Returns None when neither succeeds. The function never raises —
    callers degrade gracefully by returning a hint to the user.
    """
    raw = os.environ.get("SIM_SKILLS_ROOT")
    if raw:
        p = Path(raw)
        return p.resolve() if p.is_dir() else None

    # this file lives at <sim-cli>/src/sim/compat.py
    sibling = Path(__file__).resolve().parents[2].parent / "sim-skills"
    return sibling.resolve() if sibling.is_dir() else None


def verify_skills_layout(
    skills_root: Path,
    profiles: Iterable[tuple[str, "Profile"]] | None = None,
) -> list[str]:
    """For every (driver, profile), verify the on-disk skills tree.

    Checks per driver:
      - ``<skills_root>/<driver>/SKILL.md`` exists
      - ``<skills_root>/<driver>/base/`` exists

    Checks per profile (only when the field is set):
      - ``<skills_root>/<driver>/sdk/<active_sdk_layer>/`` exists
      - ``<skills_root>/<driver>/solver/<active_solver_layer>/`` exists

    Returns a list of human-readable mismatch lines. Empty list = healthy.
    Pass `profiles=None` to walk every profile in every driver compat.yaml.
    """
    if profiles is None:
        profiles = all_known_profiles()

    mismatches: list[str] = []
    seen_drivers: set[str] = set()

    for driver_name, profile in profiles:
        driver_dir = skills_root / driver_name

        if driver_name not in seen_drivers:
            seen_drivers.add(driver_name)
            if not driver_dir.is_dir():
                mismatches.append(
                    f"{driver_name}: missing driver dir {driver_dir}"
                )
                continue
            if not (driver_dir / "SKILL.md").is_file():
                mismatches.append(
                    f"{driver_name}: missing SKILL.md index at {driver_dir / 'SKILL.md'}"
                )
            if not (driver_dir / "base").is_dir():
                mismatches.append(
                    f"{driver_name}: missing base/ overlay at {driver_dir / 'base'}"
                )

        if profile.active_sdk_layer:
            sdk_dir = driver_dir / "sdk" / profile.active_sdk_layer
            if not sdk_dir.is_dir():
                mismatches.append(
                    f"{driver_name}/{profile.name}: missing sdk/{profile.active_sdk_layer}/ overlay"
                )
        if profile.active_solver_layer:
            solver_dir = driver_dir / "solver" / profile.active_solver_layer
            if not solver_dir.is_dir():
                mismatches.append(
                    f"{driver_name}/{profile.name}: missing solver/{profile.active_solver_layer}/ overlay"
                )

    return mismatches


def skills_block_for_profile(driver: str, profile: "Profile | None") -> dict:
    """Build the ``skills`` dict that ``/connect`` returns to the agent.

    Always returns a dict with the four keys ``root``, ``index``,
    ``active_sdk_layer``, ``active_solver_layer``. When the skills tree
    can't be located, returns ``{root: None, index: None, ..., hint: str}``
    so the LLM can produce a useful error message.
    """
    active_sdk = profile.active_sdk_layer if profile is not None else None
    active_solver = profile.active_solver_layer if profile is not None else None

    root = find_skills_root()
    driver_dir = (root / driver) if root is not None else None

    if driver_dir is None or not driver_dir.is_dir():
        # Out-of-tree plugins can bundle skills through the ``sim.skills``
        # entry-point. Prefer the external sim-skills tree when present so
        # local development overlays win, then fall back to the installed
        # plugin bundle.
        try:
            from sim.plugins import skills_dir_for
            plugin_dir = skills_dir_for(driver)
        except Exception:  # noqa: BLE001 - skills are advisory context
            plugin_dir = None
        if plugin_dir is not None:
            try:
                index = plugin_dir.joinpath("SKILL.md")
                if index.is_file():
                    return {
                        "root": str(plugin_dir),
                        "index": str(index),
                        "active_sdk_layer": active_sdk,
                        "active_solver_layer": active_solver,
                    }
            except Exception:  # noqa: BLE001 - fall through to hint
                pass

        return {
            "root": None,
            "index": None,
            "active_sdk_layer": active_sdk,
            "active_solver_layer": active_solver,
            "hint": _SKILLS_HINT,
        }

    return {
        "root": str(driver_dir),
        "index": str(driver_dir / "SKILL.md"),
        "active_sdk_layer": active_sdk,
        "active_solver_layer": active_solver,
    }
