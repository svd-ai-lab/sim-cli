"""Mechanical script using the PyMechanical SDK import."""
import ansys.mechanical.core as pm
client = pm.launch_mechanical(batch=True)
client.exit()
