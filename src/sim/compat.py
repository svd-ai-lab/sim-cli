"""Loader for per-driver `compatibility.yaml` files.

Each driver ships a `compatibility.yaml` next to its `driver.py`. This
module parses that file into a small typed surface (`Profile`,
`Compatibility`) and answers three questions:

  1. Given a detected solver version, which profile applies?
  2. What profiles does sim-cli know about across all drivers?
  3. For a given profile, which sim-skills overlay layers are active?

It is intentionally a **metadata catalogue**, not a runtime. sim-cli
runs every driver in its own process — compat.yaml exists so the CLI
can tell users "your Fluent 25R2 is supported via the
pyfluent_0_38_modern profile" and so the skills layer can resolve a
profile to its (sdk, solver) overlay paths under sim-skills/.

Public surface:
    load_compatibility(driver_dir)              -> Compatibility
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


def find_profile(profile_name: str) -> tuple[str, "Profile"] | None:
    """Walk every driver under sim/drivers/ to find a profile by name."""
    drivers_root = Path(__file__).parent / "drivers"
    if not drivers_root.is_dir():
        return None
    for child in sorted(drivers_root.iterdir()):
        compat_file = child / "compatibility.yaml"
        if not compat_file.is_file():
            continue
        try:
            compat = load_compatibility(child)
        except Exception:
            continue
        prof = compat.profile_by_name(profile_name)
        if prof is not None:
            return compat.driver, prof
    return None


def all_known_profiles() -> list[tuple[str, "Profile"]]:
    """Enumerate every profile across every driver that has a compatibility.yaml."""
    out: list[tuple[str, Profile]] = []
    drivers_root = Path(__file__).parent / "drivers"
    if not drivers_root.is_dir():
        return out
    for child in sorted(drivers_root.iterdir()):
        compat_file = child / "compatibility.yaml"
        if not compat_file.is_file():
            continue
        try:
            compat = load_compatibility(child)
        except Exception:
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


@lru_cache(maxsize=64)
def load_compatibility(driver_dir: str | Path) -> Compatibility:
    """Load and cache the compatibility.yaml for one driver directory."""
    path = Path(driver_dir) / "compatibility.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"compatibility.yaml not found for driver at {driver_dir}"
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} top-level must be a mapping")

    try:
        driver = raw["driver"]
        raw_profiles = raw.get("profiles") or []
    except KeyError as e:
        raise ValueError(f"{path} missing required field: {e}") from e

    sdk_package = raw.get("sdk_package")

    profiles: list[Profile] = []
    for i, p in enumerate(raw_profiles):
        if not isinstance(p, dict):
            raise ValueError(f"{path} profile #{i} must be a mapping, not {type(p).__name__}")
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
                f"{path} profile #{i} missing required field: {e}"
            ) from e

    return Compatibility(
        driver=driver,
        sdk_package=sdk_package,
        profiles=tuple(profiles),
    )


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
