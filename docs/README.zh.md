# sim

> LLM Agent 控制 CAE 仿真软件的统一 CLI。

[English](../README.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | **[中文](#sim)**

## 做什么的

LLM Agent 已经知道怎么写仿真脚本（PyFluent、MATLAB 等）。但缺少一个标准方式来**逐步执行、观察状态、动态决策**——对于耗时长、有状态、成本高的仿真任务，这一点至关重要。

sim 就是缺失的运行时层。类似 LLM 领域的 `ollama`，但面向 CAE 求解器。

## 架构

```
Mac / Agent                              Win / 服务器
┌──────────────┐   HTTP/Tailscale   ┌──────────────────┐
│  sim CLI     │ ────────────────>  │  sim serve       │
│  (客户端)     │ <────────────────  │  (FastAPI)       │
└──────────────┘      JSON          │       │          │
                                    │  ┌────▼────────┐ │
                                    │  │ Fluent GUI   │ │
                                    │  │ (工程师      │ │
                                    │  │  实时监控)   │ │
                                    │  └─────────────┘ │
                                    └──────────────────┘
```

## 快速开始

```bash
# 在安装了 Fluent 的机器上（如 win1）：
uv pip install "git+https://github.com/svd-ai-lab/sim-cli.git"
sim serve --host 0.0.0.0

# 从网络任意位置：
sim --host 100.90.110.79 connect --solver fluent --mode solver --ui-mode gui
sim --host 100.90.110.79 exec "solver.settings.mesh.check()"
sim --host 100.90.110.79 inspect session.summary
sim --host 100.90.110.79 disconnect
```

## 命令

| 命令 | 功能 | 类比 |
|---|---|---|
| `sim serve` | 启动 HTTP 服务器，持有求解器会话 | `ollama serve` |
| `sim connect` | 启动求解器，建立会话 | `docker start` |
| `sim exec` | 在活跃会话中执行代码片段 | `docker exec` |
| `sim inspect` | 查询实时会话状态 | `docker inspect` |
| `sim ps` | 列出活跃会话 | `docker ps` |
| `sim disconnect` | 关闭会话 | `docker stop` |
| `sim run` | 一次性脚本执行 | `docker run` |
| `sim check` | 检查求解器可用性 | `docker info` |
| `sim lint` | 执行前验证脚本 | `ruff check` |
| `sim logs` | 浏览运行历史 | `docker logs` |

## 为什么不直接跑脚本？

| 传统方式（写完就跑） | sim（逐步控制） |
|---|---|
| 写完整脚本，运行，祈祷 | 连接 → 执行 → 观察 → 决定下一步 |
| 第 2 步的错误到第 12 步才崩溃 | 每步执行后立即验证 |
| Agent 看不到求解器状态 | 每次操作之间用 `sim inspect` |
| 每次运行都重启 Fluent | 跨代码片段的持久会话 |
| 看不到 GUI | 工程师在 GUI 上实时监控，Agent 在后台驱动 |

## 支持的求解器

| 求解器 | 状态 | 后端 |
|---|---|---|
| Ansys Fluent | 可用 | PyFluent (ansys-fluent-core) |
| PyBaMM | 基础支持 | Python 直接调用 |
| COMSOL | 计划中 | MPh |
| OpenFOAM | 计划中 | — |

## 许可证

Apache-2.0
