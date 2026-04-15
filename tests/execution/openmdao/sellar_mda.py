"""OpenMDAO E2E — classical Sellar coupled-system MDA.

Two coupled disciplines:
    y1 = z1^2 + z2 + x - 0.2 * y2
    y2 = sqrt(|y1|) + z1 + z2

Inputs: z = [5, 2], x = 1.
Textbook MDA result: y1 ≈ 25.588, y2 ≈ 12.058 (Gauss-Seidel converged).
Acceptance: |y1 - 25.588| < 0.01, |y2 - 12.058| < 0.01.
"""
import json
import numpy as np
import openmdao.api as om


class SellarDis1(om.ExplicitComponent):
    def setup(self):
        self.add_input('z', val=np.zeros(2))
        self.add_input('x', val=0.0)
        self.add_input('y2', val=1.0)
        self.add_output('y1', val=1.0)

    def compute(self, inputs, outputs):
        z1, z2 = inputs['z']
        outputs['y1'] = z1 ** 2 + z2 + inputs['x'] - 0.2 * inputs['y2']


class SellarDis2(om.ExplicitComponent):
    def setup(self):
        self.add_input('z', val=np.zeros(2))
        self.add_input('y1', val=1.0)
        self.add_output('y2', val=1.0)

    def compute(self, inputs, outputs):
        z1, z2 = inputs['z']
        outputs['y2'] = abs(inputs['y1']) ** 0.5 + z1 + z2


def main():
    prob = om.Problem()
    mda = prob.model.add_subsystem('cycle', om.Group(), promotes=['*'])
    mda.add_subsystem('d1', SellarDis1(), promotes=['*'])
    mda.add_subsystem('d2', SellarDis2(), promotes=['*'])
    mda.nonlinear_solver = om.NonlinearBlockGS()

    prob.model.set_input_defaults('z', np.array([5.0, 2.0]))
    prob.model.set_input_defaults('x', 1.0)
    prob.setup()
    prob.run_model()

    y1 = float(prob['y1']); y2 = float(prob['y2'])
    print(json.dumps({
        "ok": abs(y1 - 25.588) < 0.01 and abs(y2 - 12.058) < 0.01,
        "y1": y1, "y2": y2,
        "y1_expected": 25.588, "y2_expected": 12.058,
    }))


if __name__ == "__main__":
    main()
