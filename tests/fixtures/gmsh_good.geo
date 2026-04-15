// Simple OpenCASCADE sphere - verified good .geo
SetFactory("OpenCASCADE");
Sphere(1) = {0, 0, 0, 1.0};
Physical Volume("ball") = {1};
Physical Surface("surf") = {1};
Mesh.MeshSizeMax = 0.3;
