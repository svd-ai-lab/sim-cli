"""Cantera E2E — adiabatic flame temperature for stoichiometric CH4/air.

Mechanism: gri30 (53 species, 325 reactions, included in pip wheel).
State: T=300 K, P=1 atm, CH4:O2:N2 = 1:2:7.52 (stoichiometric, air).
Process: equilibrate('HP') — constant enthalpy + pressure.

Textbook adiabatic flame temperature: ~2225 K.
Acceptance: |T_ad - 2225| < 30 K.
"""
import json
import cantera as ct


def main():
    g = ct.Solution('gri30.yaml')
    g.TPX = 300.0, ct.one_atm, 'CH4:1, O2:2, N2:7.52'
    g.equilibrate('HP')
    T = float(g.T)
    expected = 2225.0
    err = abs(T - expected)
    print(json.dumps({
        "ok": err < 30.0,
        "T_ad_K": T,
        "expected_K": expected,
        "abs_error_K": err,
        "n_species": g.n_species,
        "n_reactions": g.n_reactions,
    }))


if __name__ == "__main__":
    main()
