# Parametric study workflow #

This example shows how you can use the parametric study workflow to analyze a static mixer.

```
import os

import ansys.fluent.core as pyfluent
from ansys.fluent.core import examples
```

## Perform required imports #

Perform the required imports.

## Launch Fluent #

Launch Fluent in 3D and double precision and print Fluent version.

```
solver_session = pyfluent.launch_fluent(
    precision="double", processor_count=2, mode="solver"
)
print(solver_session.get_fluent_version())
```

## Download and read files #

Download the files for this example and read the case for the static mixer.

```
import_filename = examples.download_file(
    "Static_Mixer_main.cas.h5",
    "pyfluent/static_mixer",
    save_path=os.getcwd(),
)

solver_session.settings.file.read_case(file_name=import_filename)
```

## Set iterations #

Set the number of iterations to 100.

```
solver_session.settings.solution.run_calculation.iter_count = 100
```

## Create input parameters #

Enable parameter creation in the TUI and then create input parameters for the velocity and temperatures of inlets 1 and 2: Parameter values: Inlet1: velocity (inlet1_vel) 0.5 m/s and temperature (inlet1_temp) at 300 K Inlet2: velocity (inlet2_vel) 0.5 m/s and temperature (inlet2_temp) at 350 K

```
solver_session.settings.parameters.enable_in_tui = True

solver_session.settings.setup.named_expressions["inlet1_vel"] = {
    "output_parameter": False,
    "input_parameter": True,
    "unit": "velocity",
    "parametername": "inlet1_vel",
    "parameterid": "real-1",
    "description": "",
    "definition": "1 [m/s]",
    "name": "inlet1_vel",
}

solver_session.settings.setup.boundary_conditions.velocity_inlet["inlet1"] = {
    "momentum": {"velocity": {"value": "inlet1_vel"}}
}

solver_session.settings.setup.named_expressions["inlet1_temp"] = {
    "output_parameter": False,
    "input_parameter": True,
    "unit": "temperature",
    "parametername": "inlet1_temp",
    "parameterid": "real-2",
    "description": "",
    "definition": "300 [K]",
    "name": "inlet1_temp",
}

solver_session.settings.setup.boundary_conditions.velocity_inlet["inlet1"] = {
    "thermal": {"temperature": {"value": "inlet1_temp"}}
}

solver_session.settings.setup.named_expressions["inlet2_vel"] = {
    "output_parameter": False,
    "input_parameter": True,
    "unit": "velocity",
    "parametername": "inlet2_vel",
    "parameterid": "real-3",
    "description": "",
    "definition": "1 [m/s]",
    "name": "inlet2_vel",
}

solver_session.settings.setup.boundary_conditions.velocity_inlet["inlet2"] = {
    "momentum": {"velocity": {"value": "inlet2_vel"}}
}

solver_session.settings.setup.named_expressions["inlet2_temp"] = {
    "output_parameter": False,
    "input_parameter": True,
    "unit": "temperature",
    "parametername": "inlet2_temp",
    "parameterid": "real-4",
    "description": "",
    "definition": "350 [K]",
    "name": "inlet2_temp",
}

solver_session.settings.setup.boundary_conditions.velocity_inlet["inlet2"] = {
    "thermal": {"temperature": {"value": "inlet2_temp"}}
}
```

## Create output parameters #

Create output parameters named `outlet-temp-avg` and `outlet-vel-avg` using report definitions.

```
solver_session.settings.solution.report_definitions.surface["outlet-temp-avg"] = {}
solver_session.settings.solution.report_definitions.surface[
    "outlet-temp-avg"
].report_type = "surface-areaavg"
solver_session.settings.solution.report_definitions.surface["outlet-temp-avg"].field = (
    "temperature"
)
solver_session.settings.solution.report_definitions.surface[
    "outlet-temp-avg"
].surface_names = ["outlet"]

solver_session.settings.solution.report_definitions.surface["outlet-vel-avg"] = {}
solver_session.settings.solution.report_definitions.surface[
    "outlet-vel-avg"
].report_type = "surface-areaavg"
solver_session.settings.solution.report_definitions.surface["outlet-vel-avg"].field = (
    "velocity-magnitude"
)
solver_session.settings.solution.report_definitions.surface[
    "outlet-vel-avg"
].surface_names = ["outlet"]

solver_session.settings.parameters.output_parameters.report_definitions[
    "parameter-5"
] = {}
solver_session.settings.parameters.output_parameters.report_definitions[
    "parameter-5"
] = {"report_definition": "outlet-temp-avg"}

solver_session.settings.parameters.output_parameters.report_definitions[
    "parameter-6"
] = {}
solver_session.settings.parameters.output_parameters.report_definitions[
    "parameter-6"
] = {"report_definition": "outlet-vel-avg"}
```

## Enable convergence condition check #

Enable the convergence condition check.

```
solver_session.settings.solution.monitor.residual.options.criterion_type = "absolute"
```

## Write case #

Write the case with all settings in place.

```
solver_session.settings.file.write_case(file_name="Static_Mixer_Parameters.cas.h5")
```

## Initialize parametric study #

Initialize a parametric design point study from a Fluent session.

```
solver_session.settings.parametric_studies.initialize(project_filename="project_1")
```

![../../_images/DP_table_011.png](https://fluent.docs.pyansys.com/version/stable/_images/DP_table_011.png)

## Access and modify input parameters #

Access and modify the input parameters of the base design point.

```
solver_session.settings.parametric_studies["Static_Mixer_main-Solve"].design_points[
    "Base DP"
].input_parameters = {
    "inlet1_temp": 300,
    "inlet2_temp": 350,
    "inlet2_vel": 1,
    "inlet1_vel": 0.5,
}
```

## Update current design point #

Update the current design point.

```
solver_session.settings.parametric_studies[
    "Static_Mixer_main-Solve"
].design_points.update_current()
```

## Add design point #

Add a design point.

```
solver_session.settings.parametric_studies[
    "Static_Mixer_main-Solve"
].design_points.create(write_data=False, capture_simulation_report_data=True)

solver_session.settings.parametric_studies["Static_Mixer_main-Solve"].design_points[
    "DP1"
].input_parameters = {
    "inlet1_vel": 1,
    "inlet2_vel": 1,
    "inlet1_temp": 500,
    "inlet2_temp": 350,
}
```

## Duplicate design point #

Duplicate design point 1 to create design point 2.

```
solver_session.settings.parametric_studies[
    "Static_Mixer_main-Solve"
].design_points.duplicate(design_point="DP1")
```

## Update all design points #

Update all design points.

```
solver_session.settings.parametric_studies[
    "Static_Mixer_main-Solve"
].design_points.update_all()
```

![../../_images/DP_table_012.png](https://fluent.docs.pyansys.com/version/stable/_images/DP_table_012.png)

## Export design point table #

Export the design point table to a CSV file.

```
solver_session.settings.parametric_studies.export_design_table(
    filepath="design_point_table_study_1.csv"
)
```

## Delete design point #

Delete design point 1.

```
solver_session.settings.parametric_studies[
    "Static_Mixer_main-Solve"
].design_points.delete_design_points(design_points=["DP1"])
```

## Create parametric study #

Create another parametric study by duplicating the current one.

```
solver_session.settings.parametric_studies.duplicate(copy_design_points=True)
```

## Rename new parametric study #

Rename the newly created parametric study.

```
solver_session.settings.parametric_studies.rename(
    new="New Study", old="Static_Mixer_main-1-Solve"
)
```

## Delete old parametric study #

Delete the old parametric study.

```
solver_session.settings.parametric_studies.delete(name_list="Static_Mixer_main-Solve")
```

## Save parametric project and close Fluent #

Save the parametric project and close Fluent.

```
solver_session.settings.file.parametric_project.save_as(
    project_filename="static_mixer_study_save.flprj"
)
```

## Read saved project #

Read the previously saved project.

```
solver_session.settings.file.parametric_project.open(
    project_filename=os.path.join(os.getcwd(), "static_mixer_study_save.flprj"),
    load_case=True,
)
```

## Save current project #

Save the current project.

```
solver_session.settings.file.parametric_project.save()
```

## Save current project as a different project #

Save the current project as a different project.

```
solver_session.settings.file.parametric_project.save_as(
    project_filename="static_mixer_study_save_as.flprj"
)
```

## Export current project #

Export the current project.

```
solver_session.settings.file.parametric_project.save_as_copy(
    project_filename="static_mixer_study_export.flprj", convert_to_managed=False
)
```

## Archive current project #

Archive the current project.

```
solver_session.settings.file.parametric_project.archive(
    archive_name="static_mixer_study_archive.flprj"
)
```

## Close Fluent #

Close Fluent.

```
solver_session.exit()
```

```
Download Jupyter notebook: parametric_static_mixer_1.ipynb
Download Python source code: parametric_static_mixer_1.py
Download zipped: parametric_static_mixer_1.zip
```
