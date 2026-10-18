from ansys.aedt.core.hfss import Hfss


hfss = Hfss(project="demo.aedt", design="HFSSDesign1", non_graphical=True)
print({"project": hfss.project_name})
