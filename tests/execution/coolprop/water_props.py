"""CoolProp E2E — water saturation + latent heat at 1 atm.

Textbook (NIST steam tables):
- T_sat at 101325 Pa = 373.124 K (99.974°C)
- h_fg              = 2256.5 kJ/kg
- rho_l             ~ 958.4 kg/m^3
- rho_v             ~ 0.598 kg/m^3

Acceptance: T_sat within 0.1 K, h_fg within 1%.
"""
import json
from CoolProp.CoolProp import PropsSI


def main():
    P = 101325.0
    T_sat = float(PropsSI('T', 'P', P, 'Q', 0, 'Water'))
    h_l = float(PropsSI('H', 'P', P, 'Q', 0, 'Water'))
    h_v = float(PropsSI('H', 'P', P, 'Q', 1, 'Water'))
    h_fg = h_v - h_l
    rho_l = float(PropsSI('D', 'P', P, 'Q', 0, 'Water'))
    rho_v = float(PropsSI('D', 'P', P, 'Q', 1, 'Water'))

    print(json.dumps({
        "ok": abs(T_sat - 373.124) < 0.1 and abs(h_fg - 2.2565e6) / 2.2565e6 < 0.01,
        "T_sat_K": T_sat, "T_sat_C": T_sat - 273.15,
        "h_fg_J_per_kg": h_fg,
        "rho_l_kg_per_m3": rho_l, "rho_v_kg_per_m3": rho_v,
    }))


if __name__ == "__main__":
    main()
