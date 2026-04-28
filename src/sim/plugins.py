"""Plugin discovery, metadata, and doctor — the substrate of ``sim plugin``.

Plugins register themselves with sim-cli via three Python entry-point groups:

* ``sim.drivers`` — required. The driver class implementing
  :class:`sim.driver.DriverProtocol`. Already consumed by
  :mod:`sim.drivers`; this module does not duplicate that work.
* ``sim.skills`` — optional. A :class:`importlib.resources.abc.Traversable`
  pointing at the plugin's bundled ``_skills/`` directory. Used by
  ``sim plugin sync-skills``.
* ``sim.plugins`` — optional but recommended. A lightweight metadata dict
  (``plugin_info``) that lets ``sim plugin list`` show one row per plugin
  without importing the driver class.

This module exposes:

  list_installed_plugins()  -> list[InstalledPlugin]
  doctor(name, deep=False)  -> DoctorReport
  doctor_all(deep=False)    -> list[DoctorReport]
  plugin_info_for(name)     -> dict | None
  skills_dir_for(name)      -> Traversable | None

It deliberately does **not** install / uninstall plugins — that's
``sim plugin install``'s concern, in :mod:`sim._plugin_install`. Discovery
is read-only and side-effect-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources as _resources
from importlib.metadata import EntryPoint, entry_points
from typing import Any


# ── Entry-point groups ──────────────────────────────────────────────────────

_GROUP_DRIVERS = "sim.drivers"
_GROUP_SKILLS = "sim.skills"
_GROUP_PLUGINS = "sim.plugins"


# ── Data shapes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InstalledPlugin:
    """One row of ``sim plugin list``."""
    name: str                       # driver name, e.g. "coolprop"
    package: str                    # PyPI distribution, e.g. "sim-plugin-coolprop"
    version: str | None             # package version, e.g. "0.1.0"
    summary: str = ""               # plugin_info.summary or ""
    homepage: str = ""              # plugin_info.homepage or ""
    license_class: str = ""         # "oss" / "commercial" / ""
    solver_name: str = ""           # plugin_info.solver_name or ""
    has_skills: bool = False        # whether sim.skills entry-point present
    builtin: bool = False           # True if shipped with sim-cli (registry _BUILTIN_REGISTRY)
    driver_module: str = ""         # module path for the driver, from the registry spec

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "package": self.package,
            "version": self.version,
            "summary": self.summary,
            "homepage": self.homepage,
            "license_class": self.license_class,
            "solver_name": self.solver_name,
            "has_skills": self.has_skills,
            "builtin": self.builtin,
            "driver_module": self.driver_module,
        }


@dataclass(frozen=True)
class DoctorCheck:
    """One step in a doctor report."""
    label: str
    status: str         # "ok", "warn", "fail", "info"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "status": self.status, "message": self.message}


@dataclass
class DoctorReport:
    """The full doctor result for one plugin."""
    name: str
    plugin: InstalledPlugin | None
    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def ok(self) -> bool:
        return self.fail_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "fail_count": self.fail_count,
            "warn_count": self.warn_count,
            "plugin": self.plugin.to_dict() if self.plugin else None,
            "checks": [c.to_dict() for c in self.checks],
        }


# ── Discovery ───────────────────────────────────────────────────────────────


def _entry_points_in_group(group: str) -> list[EntryPoint]:
    """Defensive wrapper: entry-point machinery sometimes raises in odd envs."""
    try:
        return list(entry_points(group=group))
    except Exception:  # noqa: BLE001 — degrade gracefully on weird metadata states
        return []


def _ep_distribution_info(ep: EntryPoint) -> tuple[str, str | None]:
    """Return ``(package_name, version)`` for an entry point, defensively.

    The entry-point's ``.dist`` attribute may be None for in-tree dev
    installs in some Python envs; fall back to ``("", None)`` then.
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        return "", None
    name = getattr(dist, "name", None) or getattr(dist, "metadata", {}).get("Name", "")
    version = getattr(dist, "version", None)
    return (name or "", version)


def _skills_eps_by_name() -> dict[str, EntryPoint]:
    return {ep.name: ep for ep in _entry_points_in_group(_GROUP_SKILLS)}


def _plugin_info_eps_by_name() -> dict[str, EntryPoint]:
    return {ep.name: ep for ep in _entry_points_in_group(_GROUP_PLUGINS)}


def plugin_info_for(name: str) -> dict[str, Any] | None:
    """Load and return the ``plugin_info`` dict for one plugin, or None.

    Catches every exception during load — ``plugin_info`` is metadata, not
    code, so a misformed one shouldn't crash the listing.
    """
    eps = _plugin_info_eps_by_name()
    ep = eps.get(name)
    if ep is None:
        return None
    try:
        info = ep.load()
    except Exception:  # noqa: BLE001 — see docstring
        return None
    if not isinstance(info, dict):
        return None
    # Normalize: every key is a string; fill in expected keys with "".
    out = {
        "name": str(info.get("name", name)),
        "summary": str(info.get("summary", "")),
        "homepage": str(info.get("homepage", "")),
        "license_class": str(info.get("license_class", "")),
        "solver_name": str(info.get("solver_name", "")),
    }
    return out


def skills_dir_for(name: str):
    """Load and return the bundled ``_skills/<name>`` Traversable, or None.

    The ``sim.skills`` entry-point should resolve to a Traversable already
    pointing at the plugin's ``_skills/`` directory. We then descend one
    level to the per-driver subdir using the driver name.
    """
    eps = _skills_eps_by_name()
    ep = eps.get(name)
    if ep is None:
        return None
    try:
        traversable = ep.load()
    except Exception:  # noqa: BLE001
        return None
    # If the entry-point already points at <pkg>/_skills/, descend to <name>.
    candidate = traversable.joinpath(name) if hasattr(traversable, "joinpath") else None
    if candidate is not None and getattr(candidate, "is_dir", lambda: False)():
        return candidate
    # Otherwise treat it as the leaf already.
    return traversable


def list_installed_plugins() -> list[InstalledPlugin]:
    """Enumerate every driver currently registered, with metadata where present.

    Walks the ``sim.drivers`` registry (built-ins + externally discovered
    entry-points). For each entry, looks up matching ``sim.plugins`` and
    ``sim.skills`` entries. Returns one row per registered driver.
    """
    from sim.drivers import _BUILTIN_REGISTRY, _REGISTRY  # local — see compat.py

    builtin_names = {n for n, _ in _BUILTIN_REGISTRY}
    skills_eps = _skills_eps_by_name()
    info_eps = _plugin_info_eps_by_name()
    drivers_eps = {ep.name: ep for ep in _entry_points_in_group(_GROUP_DRIVERS)}

    rows: list[InstalledPlugin] = []
    for driver_name, spec in _REGISTRY:
        module_path, _, _cls = spec.rpartition(":")
        is_builtin = driver_name in builtin_names

        package, version = "", None
        ep_info: dict[str, Any] | None = None

        if not is_builtin and driver_name in drivers_eps:
            package, version = _ep_distribution_info(drivers_eps[driver_name])
        if is_builtin:
            # The host package itself ships the built-in drivers.
            package, version = _ep_distribution_info_for_host()

        if driver_name in info_eps:
            ep_info = plugin_info_for(driver_name)

        rows.append(InstalledPlugin(
            name=driver_name,
            package=package,
            version=version,
            summary=(ep_info or {}).get("summary", ""),
            homepage=(ep_info or {}).get("homepage", ""),
            license_class=(ep_info or {}).get("license_class", ""),
            solver_name=(ep_info or {}).get("solver_name", ""),
            has_skills=driver_name in skills_eps,
            builtin=is_builtin,
            driver_module=module_path,
        ))
    return rows


def _ep_distribution_info_for_host() -> tuple[str, str | None]:
    """Look up the host package (sim-cli itself) — used for built-in driver rows."""
    try:
        from importlib.metadata import distribution
        # Try the current PyPI name first; rename to sim-cli-core lands in Phase 4.
        for candidate in ("sim-cli-core", "sim-runtime"):
            try:
                dist = distribution(candidate)
                return dist.name or candidate, dist.version
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return "", None


# ── Doctor ──────────────────────────────────────────────────────────────────


def doctor(name: str, deep: bool = False) -> DoctorReport:
    """Validate one plugin end-to-end. Never raises; everything turns into checks."""
    plugins = {p.name: p for p in list_installed_plugins()}
    plugin = plugins.get(name)
    report = DoctorReport(name=name, plugin=plugin)

    if plugin is None:
        report.checks.append(DoctorCheck(
            label="registered",
            status="fail",
            message=f"no driver registered as {name!r}",
        ))
        return report

    report.checks.append(DoctorCheck(
        label="registered",
        status="ok",
        message=f"{plugin.driver_module}",
    ))

    # 2. Driver class importable.
    try:
        from sim.drivers import _resolve as _resolve_driver
        driver = _resolve_driver(name)
    except Exception as e:  # noqa: BLE001 — surface any import failure
        report.checks.append(DoctorCheck(
            label="driver_imports",
            status="fail",
            message=f"{type(e).__name__}: {e}",
        ))
        return report
    report.checks.append(DoctorCheck(
        label="driver_imports",
        status="ok",
    ))

    # 3. Structural protocol conformance.
    from sim.driver import DriverProtocol
    if isinstance(driver, DriverProtocol):
        report.checks.append(DoctorCheck(label="protocol_conforms", status="ok"))
    else:
        report.checks.append(DoctorCheck(
            label="protocol_conforms",
            status="warn",
            message="instance does not match DriverProtocol structurally",
        ))

    # 4. Skills bundle.
    if plugin.has_skills:
        skills = skills_dir_for(name)
        if skills is None:
            report.checks.append(DoctorCheck(
                label="skills_bundle",
                status="warn",
                message="sim.skills entry-point present but failed to load",
            ))
        else:
            has_skill_md = False
            try:
                has_skill_md = skills.joinpath("SKILL.md").is_file()
            except Exception:  # noqa: BLE001
                pass
            if has_skill_md:
                report.checks.append(DoctorCheck(label="skills_bundle", status="ok"))
            else:
                report.checks.append(DoctorCheck(
                    label="skills_bundle",
                    status="warn",
                    message="bundled _skills/<name>/ has no SKILL.md",
                ))
    else:
        # Built-ins typically don't have skills bundled; not a regression.
        if plugin.builtin:
            report.checks.append(DoctorCheck(
                label="skills_bundle",
                status="info",
                message="built-in driver; no bundled skills (expected)",
            ))
        else:
            report.checks.append(DoctorCheck(
                label="skills_bundle",
                status="warn",
                message="external plugin has no sim.skills entry-point",
            ))

    # 5. Compatibility.yaml present and parses.
    from sim.compat import load_compatibility_by_name
    compat = load_compatibility_by_name(name)
    if compat is None:
        # Many drivers legitimately have no compat.yaml (SDK-less / version-insensitive).
        report.checks.append(DoctorCheck(
            label="compatibility_yaml",
            status="info",
            message="no compatibility.yaml (driver is SDK-less or version-insensitive)",
        ))
    else:
        report.checks.append(DoctorCheck(
            label="compatibility_yaml",
            status="ok",
            message=f"{len(compat.profiles)} profile(s)",
        ))

    # 6. Optional deep check: detect_installed.
    if deep:
        try:
            from sim.compat import safe_detect_installed
            installs = safe_detect_installed(driver)
            if installs:
                report.checks.append(DoctorCheck(
                    label="solver_detected",
                    status="ok",
                    message=f"{len(installs)} install(s)",
                ))
            else:
                report.checks.append(DoctorCheck(
                    label="solver_detected",
                    status="info",
                    message="no installation found on this host",
                ))
        except Exception as e:  # noqa: BLE001
            report.checks.append(DoctorCheck(
                label="solver_detected",
                status="warn",
                message=f"detect_installed raised {type(e).__name__}: {e}",
            ))

    return report


def doctor_all(deep: bool = False) -> list[DoctorReport]:
    """Run doctor on every registered driver. Order matches the registry."""
    return [doctor(p.name, deep=deep) for p in list_installed_plugins()]


# ── Skills sync ─────────────────────────────────────────────────────────────


def sync_skills_to(target_dir, *, copy: bool = False) -> dict[str, Any]:
    """Materialize every installed plugin's ``_skills/<name>/`` under ``target_dir``.

    Default mode is symlink (idempotent, near-free); ``copy=True`` falls
    back to recursive copy for environments where symlinks are blocked
    (Windows without developer mode).

    Returns ``{"ok": bool, "linked": [...], "copied": [...], "skipped": [...]}``.
    Skips drivers without a ``sim.skills`` entry-point (built-ins, OSS plugins
    that haven't shipped skills yet).
    """
    from pathlib import Path

    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    linked: list[str] = []
    copied: list[str] = []
    skipped: list[str] = []

    for plugin in list_installed_plugins():
        if not plugin.has_skills:
            skipped.append(plugin.name)
            continue
        skills = skills_dir_for(plugin.name)
        if skills is None:
            skipped.append(plugin.name)
            continue

        # Resolve the Traversable to a real filesystem path. importlib.resources
        # returns a MultiplexedPath / PosixPath / WindowsPath depending on the
        # install type. _resources.as_file() yields a real path.
        with _resources.as_file(skills) as src_path:
            dest = target / plugin.name
            if dest.is_symlink() or dest.exists():
                try:
                    if dest.is_symlink():
                        dest.unlink()
                    elif dest.is_dir():
                        import shutil
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                except OSError:
                    skipped.append(plugin.name)
                    continue

            if copy:
                import shutil
                shutil.copytree(src_path, dest)
                copied.append(plugin.name)
            else:
                try:
                    dest.symlink_to(src_path, target_is_directory=True)
                    linked.append(plugin.name)
                except (OSError, NotImplementedError):
                    # Windows / no privilege — fall back to copy.
                    import shutil
                    shutil.copytree(src_path, dest)
                    copied.append(plugin.name)

    return {
        "ok": True,
        "target": str(target),
        "linked": linked,
        "copied": copied,
        "skipped": skipped,
    }
