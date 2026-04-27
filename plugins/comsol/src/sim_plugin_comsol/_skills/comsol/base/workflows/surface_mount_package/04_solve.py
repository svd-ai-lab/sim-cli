"""Create stationary study and solve the heat transfer problem."""

std = model.study().create("std1")
std.create("stat", "Stationary")
std.label("Steady-State Thermal")

model.sol().create("sol1")
model.sol("sol1").createAutoSequence("std1")
model.sol("sol1").runAll()

_result = {"step": "solve", "study": "stationary", "status": "ok"}
