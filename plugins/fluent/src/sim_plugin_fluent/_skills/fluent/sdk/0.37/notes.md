# PyFluent 0.37 (legacy)

This layer is a stub. The 0.37 line uses the older `cell_zone.<zone>.material`
accessor (no `.general.material`), which differs from the patterns shown
in `base/snippets/`. Until a 0.37-curated set lands here, treat the
following base/ snippets as known-incompatible on 0.37 and translate by
hand using the rule:

    # 0.38+
    cell_zone.fluid["fluid"].general.material = "water-liquid"
    # 0.37
    cell_zone.fluid["fluid"].material = "water-liquid"

Material assignment is the only place this dialect difference bites
in the EX-01 mixing-elbow workflow. Energy/turbulence/BC patterns are
identical across both lines.
