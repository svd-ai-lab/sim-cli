# Simple well-formed ICEM CFD Tcl script (fixture)
ic_load_tetin "geometry.tin"
ic_uns_set_mesh_params -global_size 0.1
ic_uns_run_mesh
ic_save_mesh "output.msh"
puts "done"
