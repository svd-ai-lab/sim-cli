import pyaedt


hfss = pyaedt.Hfss(project="demo.aedt", design="HFSSDesign1", non_graphical=True)
print(hfss.design_name)
