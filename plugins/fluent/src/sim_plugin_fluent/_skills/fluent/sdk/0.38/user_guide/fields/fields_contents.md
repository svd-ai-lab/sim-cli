# Fields #

PyFluent provides several services that allow you to access field data in different ways. Every PyFluent solution and meshing Session object contains a `fields` object. In both solution and meshing modes, the `fields` object contains `field_data` and `field_data_streaming` children. In `solution` mode, the `fields` object also has `reduction` , `solution_variable_data` and `solution_variable_info` children.

To help decide between using `field_data` and `solution_variable_data` , refer to the dedicated comparison guide.

This guide explains:

- The surface-centric vs. zone-centric perspectives.
- Read vs. read/write capabilities.
- Typical use cases for each API.
- Performance and scope considerations.
