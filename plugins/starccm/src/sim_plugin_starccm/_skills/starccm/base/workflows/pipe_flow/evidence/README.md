# Star-CCM+ E2E 测试证据 — Pipe Flow Mesh

**日期**: 2026-04-13  
**求解器**: Simcenter STAR-CCM+ 2602 Build 21.02.007

## 模型

| 参数 | 值 |
|------|-----|
| 几何 | SimpleCylinderPart, R=0.05m, L=1.0m |
| 网格器 | Surface Remesher + Trimmer |
| 基础尺寸 | 0.01m |

## 网格结果

| 指标 | 值 |
|------|-----|
| 表面三角形 | 8,730 |
| 体网格单元 | 4,768 |
| 面 | 13,404 |
| 顶点 | 6,897 |
| 最差三角形质量 | 0.7193 |
| minFaceValidity | 1.000000 |
| minCellQuality | 1.000000 |
| 网格生成耗时 | 0.79s |
| 总运行耗时 | ~17s（含 JVM 启动 + license checkout）|

## 验证

- 网格质量指标全部为 1.0（完美） ✓
- 无交叉面、无退化单元 ✓
- exit_code=0, ok=true ✓
- 场景图片成功渲染（mesa 离屏） ✓

## 文件

- `pipe_mesh_scene.png` — **Star-CCM+ 渲染的 Trimmer 网格场景**（mesa 离屏导出）
- `e2e_summary.json` — 结构化结果数据
- `run/pipe_flow.sim` — Star-CCM+ 仿真文件（可用 GUI 打开）
- `run/starccm_pipe_flow_visual.java` — 完整宏（geometry + mesh + scene + export）
- `run/export_mesh_scene.java` — 场景导出宏
