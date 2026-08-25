# DOBOT CR5 robot-description dependency

This directory supplies the `dobot_rviz` package referenced by
`cr5_moveit/config/cr5_robot.urdf.xacro`.

- Upstream: <https://github.com/Dobot-Arm/DOBOT_6Axis_ROS2_V4>
- Pinned commit: `0f67ed938c0cec4ed0808af759ddbb608e573dbe`
- Imported subset: `package.xml`, `CMakeLists.txt`, `urdf/cr5_robot.urdf`,
  `meshes/cr5/{base_link,J1,J2,J3,J4,J5,J6}.STL`
- Repository license: MIT; the upstream `LICENSE` file is preserved here.

`CMakeLists.txt` was narrowed locally to install only `urdf/`, `meshes/`,
`LICENSE`, and this provenance file. The upstream package also references
launch/RViz/relay resources that are intentionally not part of this minimal
description dependency. The upstream package manifest still contains a TODO
license field, while the repository root is MIT and some sibling packages say
BSD; obtain vendor clarification before public redistribution of the meshes.

The asset is named CR5 upstream. The photographed robot is DOBOT CR5A
(`DT-CR050A-0`). Until their kinematic and mesh equivalence is independently
verified, use this package as a provisional articulated simulation skeleton,
not as evidence that the CR5A geometry is exact. CR5AF is a different CRAF
force-control model and is not an acceptable substitute.
