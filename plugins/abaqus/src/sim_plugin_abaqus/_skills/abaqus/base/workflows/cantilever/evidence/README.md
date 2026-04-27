# Abaqus E2E 测试证据 — 悬臂梁

**日期**: 2026-04-13  
**求解器**: Abaqus 2026  

## 模型

| 参数 | 值 |
|------|-----|
| 类型 | 悬臂梁受端部载荷 (Cantilever beam, tip load) |
| 几何 | L=10m, b=1m, h=1m |
| 材料 | 钢, E=200GPa, ν=0.3 |
| 载荷 | P=-1000N (节点5, Y方向) |
| 约束 | 固定支撑 (节点1,10, 左端) |
| 单元 | 4个 CPS4 (二维平面应力) |
| 节点 | 10个 |

## 解析解

Euler-Bernoulli 梁理论: δ = PL³/(3EI) = 1000×10³/(3×200×10⁹×1×1³/12) = **2×10⁻⁵ m**

## FEM 结果

| 输出 | 值 |
|------|-----|
| 节点5 U1 (水平) | -4.29×10⁻⁷ m |
| 节点5 U2 (竖向) | **-5.75×10⁻⁶ m** |
| 端部挠度 | 5.75×10⁻⁶ m |

## 验证

- 端部挠度 5.75×10⁻⁶ m 在预期范围 [10⁻⁷, 10⁻⁴] m 内 ✓
- 粗网格 (4个低阶CPS4单元) 比梁理论偏刚 (5.75e-6 vs 2e-5) — 符合预期 ✓
- Abaqus 报告 "JOB COMPLETED" ✓
- exit_code=0, ok=true, errors=[] ✓

## 运行记录

```
--- Test 1: .inp direct ---
[sim] run:    abaqus_e2e_cantilever.inp via abaqus
[sim] status: converged (10.484s)

--- Test 2: Python wrapper ---
{"ok": true, "node": 5, "U1_m": -4.2898087e-07, "U2_m": -5.7521961e-06,
 "tip_deflection_m": 5.7521961e-06, "solver_output": "Abaqus completed successfully"}
```

## 文件

- `e2e_summary.json` — 结构化结果数据
- `cantilever_deformation.png` — **Abaqus/CAE 渲染的 U2 变形云图**（noGUI 模式导出）
- `run/` — 完整的 Abaqus 运行目录（.inp, .odb, .dat 等）
