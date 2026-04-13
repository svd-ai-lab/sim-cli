*KEYWORD
*TITLE
Simple tensile bar test
$
$ Units: mm, s, tonne, N, MPa
$
*PARAMETER
R endtime  1.0e-03
$
*CONTROL_TERMINATION
&endtime
$
*DATABASE_BINARY_D3PLOT
 1.0e-04
$
*MAT_ELASTIC
$      mid        ro         e        pr
         1  7.85e-09    210000       0.3
$
*SECTION_SOLID
$    secid    elform
         1         1
$
*PART
$ Simple bar
$      pid     secid       mid
         1         1         1
$
*NODE
$    nid               x               y               z
       1       0.000000       0.000000       0.000000
       2      10.000000       0.000000       0.000000
       3      10.000000      10.000000       0.000000
       4       0.000000      10.000000       0.000000
       5       0.000000       0.000000      50.000000
       6      10.000000       0.000000      50.000000
       7      10.000000      10.000000      50.000000
       8       0.000000      10.000000      50.000000
$
*ELEMENT_SOLID
$    eid     pid      n1      n2      n3      n4      n5      n6      n7      n8
       1       1       1       2       3       4       5       6       7       8
$
*BOUNDARY_SPC_SET
$     nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz
         1         0         1         1         1         0         0         0
$
*SET_NODE_LIST
$      sid
         1
         1,         2,         3,         4
$
*LOAD_NODE_POINT
$     nid       dof     lcid        sf
         5         3         1       100
         6         3         1       100
         7         3         1       100
         8         3         1       100
$
*DEFINE_CURVE
$     lcid
         1
              0.0,          0.0
           1.0e-3,          1.0
$
*END
