"""Minimal OpenMDAO script — y = 2*x via ExecComp."""
import json
import openmdao.api as om

prob = om.Problem()
prob.model.add_subsystem('comp', om.ExecComp('y = 2*x'), promotes=['*'])
prob.setup()
prob['x'] = 3.0
prob.run_model()
print(json.dumps({"ok": True, "y": float(prob['y'])}))
