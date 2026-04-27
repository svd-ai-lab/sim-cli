"""Mock COMSOL/MPh script for testing — does not require COMSOL."""
import json

import mph

client = mph.start()
model = client.load("capacitor.mph")
model.solve()

# Extract results
C = model.evaluate("es.C11")
print(json.dumps({"capacitance_F": round(float(C), 6), "model": "capacitor"}))
