"""Create 3D surface temperature plot."""
pg = model.result().create("pg1", "PlotGroup3D")
pg.label("Temperature Distribution")
surf = pg.create("surf1", "Surface")
surf.set("expr", "T")
surf.set("colortable", "ThermalLight")
surf.set("unit", "degC")
pg.run()

_result = {"step": "plot", "plot": "Temperature Distribution", "status": "ok"}
