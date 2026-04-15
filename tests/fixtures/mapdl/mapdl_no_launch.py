"""Imports pymapdl but never launches — lint should warn."""
import ansys.mapdl.core as pm

print(pm.__version__)
