"""scikit-rf E2E — verify standard loads on a 50-Ω line.

Theory:
- Short:  S11 = -1 + 0j (perfect reflection, π phase shift)
- Open:   S11 = +1 + 0j (perfect reflection, no phase shift)
- Match:  S11 =  0 + 0j (no reflection)

Acceptance: |S11(short) - (-1)| < 1e-12, |S11(open) - 1| < 1e-12,
            |S11(match)| < 1e-12.
"""
import json
import skrf as rf


def main():
    freq = rf.Frequency(1, 10, 11, 'GHz')
    line = rf.media.DefinedGammaZ0(freq, z0=50.0)

    s = line.short().s[5, 0, 0]
    o = line.open().s[5, 0, 0]
    m = line.match().s[5, 0, 0]

    print(json.dumps({
        "ok": (abs(s + 1) < 1e-12 and abs(o - 1) < 1e-12 and abs(m) < 1e-12),
        "S11_short_re": float(s.real), "S11_short_im": float(s.imag),
        "S11_open_re":  float(o.real), "S11_open_im":  float(o.imag),
        "S11_match_re": float(m.real), "S11_match_im": float(m.imag),
    }))


if __name__ == "__main__":
    main()
