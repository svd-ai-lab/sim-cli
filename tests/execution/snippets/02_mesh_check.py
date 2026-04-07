# Step 2: Run mesh check. Verifies no negative volumes or other mesh errors.
solver.settings.mesh.check()
_result = {"step": "mesh-check", "ok": True}
