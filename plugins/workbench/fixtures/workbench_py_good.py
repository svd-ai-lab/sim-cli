"""Workbench script using Python API."""
import ansys.workbench.core as wb

wb.launch_workbench()
wb.run_script("setup.wbjn")
wb.download_file("output.txt")
