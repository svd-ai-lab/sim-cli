"""
手工集成演示脚本（Manual Integration Demo）：
通过 PyFluentDriver API 运行 Watertight Geometry Meshing 完整流程。

定位：
  - 手工集成演示脚本，不作为自动化测试运行，不被 pytest 收集。
  - 需要真实 Ansys Fluent 2024 R1 环境 + GUI 模式下目视确认。

验证层次说明：
  层次 A — Driver API 层打通（本脚本验证范围）：
    通过 PyFluentDriver Python API 直接调用 launch/run/query，
    证明 driver 层逻辑和 runtime 日志写入（.sim/runs/*.json）可用。

  层次 B — sim CLI subprocess runtime（本脚本不验证）：
    通过 `sim run <此脚本> --solver=fluent` 触发时，
    仅证明 sim CLI 可以用 subprocess 调用此脚本，
    不等于 sim 原生支持交互式 pyfluent runtime。

验证需求：
  - 所有启动步骤以 GUI 模式运行（driver.launch ui_mode="gui"）
  - 每个 workflow 步骤通过 driver.run(code, label) 执行，日志写入 .sim/runs/
  - 流程结束后通过 driver.query() 验证结构化结果

运行方式（直接 Python，验证 Driver API 层）：
    python src/sim/drivers/pyfluent/examples/demo_watertight_via_driver.py

运行方式（通过 sim CLI，验证 subprocess 调用层）：
    sim check pyfluent   # 注：sim connect = 包可用性检查，不启动 session
    sim run src/sim/drivers/pyfluent/examples/demo_watertight_via_driver.py --solver=fluent --json

参考文档：
  - specs/pyfluent_driver_v0.md  §11.3 Meshing Case 1
  - src/sim/drivers/pyfluent/reference/pyfluent_user_guide/meshing/meshing_workflows.md
"""
from __future__ import annotations

import json
import sys

from sim.drivers.fluent.driver import PyFluentDriver

SEP = "─" * 60

# ── 初始化 driver ─────────────────────────────────────────────────
driver = PyFluentDriver()

# ── Step 0: 包可用性检查 ─────────────────────────────────────────
print("\n[Step 0] ansys-fluent-core 包可用性检查")
print(SEP)
info = driver.connect()
print(f"  status  = {info.status}")
print(f"  version = {info.version}")
print(f"  message = {info.message}")
if info.status != "ok":
    print("  ERROR: pyfluent 不可用，退出")
    sys.exit(1)

# ── Step 1: 启动 meshing session（GUI 模式）───────────────────────
print("\n[Step 1] 启动 meshing session（GUI 模式，约 30–60 秒）")
print(SEP)
print("  调用 driver.launch(mode='meshing', ui_mode='gui') ...")
try:
    session_info = driver.launch(mode="meshing", ui_mode="gui")
except RuntimeError as e:
    print(f"  ERROR: {e}")
    sys.exit(1)
print(json.dumps(session_info, indent=4))

# ── Step 2: query session.summary ────────────────────────────────
print("\n[Step 2] query('session.summary')")
print(SEP)
print(json.dumps(driver.query("session.summary"), indent=4))

# ── Step 3: 下载几何文件 ──────────────────────────────────────────
print("\n[Step 3] 下载几何文件 mixing_elbow.pmdb")
print(SEP)
r = driver.run(
    code=(
        "from ansys.fluent.core import examples\n"
        "import_file = examples.download_file('mixing_elbow.pmdb', 'pyfluent/mixing_elbow')\n"
        "print(f'  下载路径 = {import_file}')\n"
        "_result = {'import_file': str(import_file)}"
    ),
    label="download-geometry",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: 下载失败，退出")
    sys.exit(1)
import_file = r["result"]["import_file"]
print(f"  >>> import_file = {import_file}")

# ── Step 4: 初始化 Watertight Geometry 工作流 ─────────────────────
print("\n[Step 4] 初始化 Watertight Geometry 工作流")
print(SEP)
r = driver.run(
    code=(
        "workflow = meshing.workflow\n"
        "workflow.InitializeWorkflow(WorkflowType='Watertight Geometry')\n"
        "tasks = workflow.TaskObject\n"
        "task_names = list(tasks.get_state().keys())\n"
        "print(f'  任务列表: {task_names}')\n"
        "_result = {'task_count': len(task_names), 'tasks': task_names}"
    ),
    label="init-watertight-workflow",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: 工作流初始化失败，退出")
    sys.exit(1)

# ── Step 5: Import Geometry ───────────────────────────────────────
print("\n[Step 5] Import Geometry（导入几何，单位 in）")
print(SEP)
r = driver.run(
    code=(
        f"import_file = r'{import_file}'\n"
        "tasks = meshing.workflow.TaskObject\n"
        "import_geometry = tasks['Import Geometry']\n"
        "import_geometry.Arguments.set_state({'FileName': import_file, 'LengthUnit': 'in'})\n"
        "import_geometry.Execute()\n"
        "print('  Import Geometry 执行成功')\n"
        "_result = {'import_geometry_done': True, 'file': import_file}"
    ),
    label="import-geometry",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Import Geometry 失败，退出")
    sys.exit(1)

# ── Step 6: Add Local Sizing ──────────────────────────────────────
print("\n[Step 6] Add Local Sizing（添加局部尺寸）")
print(SEP)
r = driver.run(
    code=(
        "tasks = meshing.workflow.TaskObject\n"
        "add_local_sizing = tasks['Add Local Sizing']\n"
        "add_local_sizing.AddChildToTask()\n"
        "add_local_sizing.Execute()\n"
        "print('  Add Local Sizing 执行成功')\n"
        "_result = {'add_local_sizing_done': True}"
    ),
    label="add-local-sizing",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Add Local Sizing 失败，退出")
    sys.exit(1)

# ── Step 7: Generate Surface Mesh ─────────────────────────────────
print("\n[Step 7] Generate Surface Mesh（MaxSize=0.3）")
print(SEP)
r = driver.run(
    code=(
        "tasks = meshing.workflow.TaskObject\n"
        "surf_mesh = tasks['Generate the Surface Mesh']\n"
        "surf_mesh.Arguments.set_state({'CFDSurfaceMeshControls': {'MaxSize': 0.3}})\n"
        "surf_mesh.Execute()\n"
        "print('  Generate Surface Mesh 执行成功')\n"
        "_result = {'surface_mesh_done': True}"
    ),
    label="generate-surface-mesh",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Generate Surface Mesh 失败，退出")
    sys.exit(1)

# ── Step 8: Describe Geometry ─────────────────────────────────────
print("\n[Step 8] Describe Geometry（fluid only）")
print(SEP)
r = driver.run(
    code=(
        "tasks = meshing.workflow.TaskObject\n"
        "describe_geometry = tasks['Describe Geometry']\n"
        "describe_geometry.UpdateChildTasks(SetupTypeChanged=False)\n"
        "describe_geometry.Arguments.set_state({\n"
        "    'SetupType': 'The geometry consists of only fluid regions with no voids'\n"
        "})\n"
        "describe_geometry.UpdateChildTasks(SetupTypeChanged=True)\n"
        "describe_geometry.Execute()\n"
        "print('  Describe Geometry 执行成功')\n"
        "_result = {'describe_geometry_done': True}"
    ),
    label="describe-geometry",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Describe Geometry 失败，退出")
    sys.exit(1)

# ── Step 9: Update Boundaries ─────────────────────────────────────
print("\n[Step 9] Update Boundaries")
print(SEP)
r = driver.run(
    code=(
        "meshing.workflow.TaskObject['Update Boundaries'].Execute()\n"
        "print('  Update Boundaries 执行成功')\n"
        "_result = {'update_boundaries_done': True}"
    ),
    label="update-boundaries",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Update Boundaries 失败，退出")
    sys.exit(1)

# ── Step 10: Update Regions ───────────────────────────────────────
print("\n[Step 10] Update Regions")
print(SEP)
r = driver.run(
    code=(
        "meshing.workflow.TaskObject['Update Regions'].Execute()\n"
        "print('  Update Regions 执行成功')\n"
        "_result = {'update_regions_done': True}"
    ),
    label="update-regions",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Update Regions 失败，退出")
    sys.exit(1)

# ── Step 11: Add Boundary Layers ──────────────────────────────────
print("\n[Step 11] Add Boundary Layers（smooth-transition）")
print(SEP)
r = driver.run(
    code=(
        "tasks = meshing.workflow.TaskObject\n"
        "add_bl = tasks['Add Boundary Layers']\n"
        "add_bl.AddChildToTask()\n"
        "add_bl.InsertCompoundChildTask()\n"
        "tasks['smooth-transition_1'].Arguments.set_state({'BLControlName': 'smooth-transition_1'})\n"
        "add_bl.Arguments.set_state({})\n"
        "tasks['smooth-transition_1'].Execute()\n"
        "print('  Add Boundary Layers 执行成功')\n"
        "_result = {'boundary_layers_done': True}"
    ),
    label="add-boundary-layers",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Add Boundary Layers 失败，退出")
    sys.exit(1)

# ── Step 12: Generate Volume Mesh ─────────────────────────────────
print("\n[Step 12] Generate Volume Mesh（poly-hexcore）")
print(SEP)
r = driver.run(
    code=(
        "tasks = meshing.workflow.TaskObject\n"
        "vol_mesh = tasks['Generate the Volume Mesh']\n"
        "vol_mesh.Arguments.set_state({\n"
        "    'VolumeFill': 'poly-hexcore',\n"
        "    'VolumeFillControls': {'HexMaxCellLength': 0.3},\n"
        "})\n"
        "vol_mesh.Execute()\n"
        "print('  Generate Volume Mesh 执行成功')\n"
        "_result = {'volume_mesh_done': True}"
    ),
    label="generate-volume-mesh",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Generate Volume Mesh 失败，退出")
    sys.exit(1)

# ── Step 13: Switch to Solver ─────────────────────────────────────
print("\n[Step 13] Switch to Solver")
print(SEP)
r = driver.run(
    code=(
        "solver_session = meshing.switch_to_solver()\n"
        "print(f'  切换成功，solver 类型 = {type(solver_session).__name__}')\n"
        "_result = {'switch_to_solver_done': True, 'solver_type': type(solver_session).__name__}"
    ),
    label="switch-to-solver",
)
print(json.dumps(r, indent=4))
if not r["ok"]:
    print("  ERROR: Switch to Solver 失败，退出")
    sys.exit(1)

# ── Step 14: query workflow.summary ───────────────────────────────
print("\n[Step 14] query('workflow.summary')")
print(SEP)
print(json.dumps(driver.query("workflow.summary"), indent=4))

# ── Step 15: query last.result ────────────────────────────────────
print("\n[Step 15] query('last.result')")
print(SEP)
print(json.dumps(driver.query("last.result"), indent=4))

# ── 完成 ─────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("全部步骤通过 — Watertight Geometry Meshing 流程完成")
print("日志已写入 .sim/runs/*.json")
print(f"{'='*60}")
