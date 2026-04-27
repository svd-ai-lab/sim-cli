# Step 3: Enable energy equation and set viscous model to realizable k-epsilon.
solver.settings.setup.models.energy.enabled = True

viscous = solver.settings.setup.models.viscous
viscous.model = "k-epsilon"
viscous.k_epsilon_model = "realizable"

energy_on = bool(solver.settings.setup.models.energy.enabled)
_result = {
    "step": "setup-physics",
    "energy_enabled": energy_on,
    "viscous_model": "k-epsilon-realizable",
    "ok": True,
}
