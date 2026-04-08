"""Loader for per-driver `compatibility.yaml` files.

Each driver ships a `compatibility.yaml` next to its `driver.py`. This module
parses that file into typed dataclasses and exposes the resolution rules
defined in `docs/architecture/version-compat.md`.

The loader is intentionally pure-Python and dependency-light:
- requires only `pyyaml` and `packaging`
- never imports the SDK (we may run before any SDK is installed)
- safe to call repeatedly (results are cached per file path)

Public surface:
    load_compatibility(driver_dir)              -> Compatibility
    Compatibility.resolve(solver_version)       -> ResolutionResult
    Compatibility.profile_by_name(name)         -> Profile | None
    Compatibility.profile_for_sdk(sdk_version)  -> Profile | None
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


# ── data model ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Profile:
    """A named (SDK range, solver version list) tuple from compatibility.yaml."""
    name: str
    sdk: str                       # PEP 440 specifier, e.g. ">=0.38,<0.39"
    solver_versions: tuple[str, ...]
    skill_revision: str
    runner_module: str
    extras_alias: str | None = None
    notes: str = ""

    def matches_solver(self, solver_version: str) -> bool:
        """True if this profile lists the given solver version."""
        # Solver versions are matched as strings, not PEP 440 — vendor versioning
        # is messy (e.g. Fluent reports "25.2.0", users say "25R2"). The yaml
        # author writes the canonical short form ("25.2") and the loader's
        # normalize() helper coerces detected versions before comparison.
        return _normalize_solver_version(solver_version) in self.solver_versions

    def matches_sdk(self, sdk_version: str) -> bool:
        """True if this profile's SDK specifier accepts the given SDK version."""
        try:
            spec = SpecifierSet(self.sdk)
            return Version(sdk_version) in spec
        except (InvalidSpecifier, InvalidVersion):
            return False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "sdk": self.sdk,
            "solver_versions": list(self.solver_versions),
            "skill_revision": self.skill_revision,
            "runner_module": self.runner_module,
            "extras_alias": self.extras_alias,
            "notes": self.notes.strip(),
        }


@dataclass(frozen=True)
class DeprecatedProfile:
    name: str
    reason: str
    last_supported_in_sim_cli: str
    migrate_to: str | None = None

    def to_dict(self) -> dict:
        return {
            "profile": self.name,
            "reason": self.reason,
            "last_supported_in_sim_cli": self.last_supported_in_sim_cli,
            "migrate_to": self.migrate_to,
        }


@dataclass(frozen=True)
class Compatibility:
    """Parsed compatibility.yaml for one driver."""
    driver: str
    sdk_package: str
    profiles: tuple[Profile, ...]
    deprecated: tuple[DeprecatedProfile, ...] = field(default_factory=tuple)

    def profile_by_name(self, name: str) -> Profile | None:
        for p in self.profiles:
            if p.name == name:
                return p
        return None

    def profile_for_sdk(self, sdk_version: str) -> Profile | None:
        """First profile whose SDK specifier accepts the given installed SDK."""
        for p in self.profiles:
            if p.matches_sdk(sdk_version):
                return p
        return None

    def resolve(self, solver_version: str) -> ResolutionResult:
        """Pick the preferred profile for a detected solver version.

        Resolution rules (from docs/architecture/version-compat.md §6.2):
          1. Walk profiles in declaration order.
          2. The first profile whose solver_versions contains V is the
             preferred match.
          3. If multiple profiles list the same V, the first wins; the
             others are returned as `also_matching` so the caller can
             surface them with --profile override hints.
          4. If no profile matches, return `unsupported` with the
             deprecated table for hints.
        """
        normalized = _normalize_solver_version(solver_version)
        matches = [p for p in self.profiles if normalized in p.solver_versions]
        if matches:
            return ResolutionResult(
                solver_version=normalized,
                preferred=matches[0],
                also_matching=tuple(matches[1:]),
                deprecated_hits=(),
                status="ok",
            )

        deprecated_hits = tuple(
            d for d in self.deprecated if d.name  # placeholder for future per-version dep info
        )
        return ResolutionResult(
            solver_version=normalized,
            preferred=None,
            also_matching=(),
            deprecated_hits=deprecated_hits,
            status="unsupported",
        )


@dataclass(frozen=True)
class ResolutionResult:
    solver_version: str
    preferred: Profile | None
    also_matching: tuple[Profile, ...]
    deprecated_hits: tuple[DeprecatedProfile, ...]
    status: str  # "ok" or "unsupported"

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return {
            "solver_version": self.solver_version,
            "status": self.status,
            "preferred": self.preferred.to_dict() if self.preferred else None,
            "also_matching": [p.to_dict() for p in self.also_matching],
            "deprecated_hits": [d.to_dict() for d in self.deprecated_hits],
        }


# ── loader ──────────────────────────────────────────────────────────────────


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

    # "v252" or "252" form (Ansys release codes)
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 3 and ("v" + digits in s.lower() or s == digits):
        return f"{digits[:2]}.{digits[2]}"

    # "2025 R2" / "2025R2" form
    s_compact = s.replace(" ", "").lower()
    if "r" in s_compact:
        year_part, _, rel_part = s_compact.partition("r")
        if year_part.isdigit() and rel_part.isdigit() and len(year_part) == 4:
            return f"{year_part[2:]}.{rel_part}"

    # "25.2.0" -> "25.2"
    parts = s.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}"

    return s


def find_profile(profile_name: str) -> tuple[str, "Profile"] | None:
    """Walk every driver under sim/drivers/ to find a profile by name.

    Returns (driver_name, profile) on hit, None on miss. Used by
    `sim env install <profile>` to figure out which driver the profile
    belongs to without making the user spell out --solver.
    """
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
    """Enumerate every profile across every driver that has a compatibility.yaml.

    Used by `sim env list` to compare bootstrapped envs against the catalogue.
    """
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
    """Call driver.detect_installed() defensively.

    Drivers that have not yet implemented the new protocol method return
    an empty list instead of crashing the caller. Any exception inside the
    detector also degrades to []. This keeps `sim check` resilient as we
    migrate drivers one at a time.
    """
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
    """Load and cache the compatibility.yaml for one driver directory.

    Args:
        driver_dir: filesystem path to e.g. `src/sim/drivers/fluent/`.

    Raises:
        FileNotFoundError if compatibility.yaml does not exist.
        ValueError if the file is malformed.
    """
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
        sdk_package = raw["sdk_package"]
        raw_profiles = raw.get("profiles") or []
    except KeyError as e:
        raise ValueError(f"{path} missing required field: {e}") from e

    profiles: list[Profile] = []
    for i, p in enumerate(raw_profiles):
        try:
            profiles.append(
                Profile(
                    name=p["name"],
                    sdk=p["sdk"],
                    solver_versions=tuple(
                        _normalize_solver_version(v) for v in p["solver_versions"]
                    ),
                    skill_revision=p["skill_revision"],
                    runner_module=p["runner_module"],
                    extras_alias=p.get("extras_alias"),
                    notes=p.get("notes", "") or "",
                )
            )
        except KeyError as e:
            raise ValueError(
                f"{path} profile #{i} missing required field: {e}"
            ) from e

    deprecated: list[DeprecatedProfile] = []
    for d in raw.get("deprecated") or []:
        deprecated.append(
            DeprecatedProfile(
                name=d.get("profile", "?"),
                reason=d.get("reason", ""),
                last_supported_in_sim_cli=str(d.get("last_supported_in_sim_cli", "")),
                migrate_to=d.get("migrate_to"),
            )
        )

    return Compatibility(
        driver=driver,
        sdk_package=sdk_package,
        profiles=tuple(profiles),
        deprecated=tuple(deprecated),
    )
