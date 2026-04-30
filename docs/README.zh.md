<div align="center">

<img src="../assets/banner.svg" alt="sim — 让每一款工程软件都为 Agent 而生" width="820">

<br>

**让每一款工程软件，都为 Agent 而生。**

*今天的 CAD/CAE 软件是为工程师点鼠标设计的。*
*明天的用户是 AI 智能体 —— 它需要一条进来的路。*

<p align="center">
  <a href="#-快速开始"><img src="https://img.shields.io/badge/快速开始-2_分钟-3b82f6?style=for-the-badge" alt="快速开始"></a>
  <a href="#-求解器注册表"><img src="https://img.shields.io/badge/求解器-持续扩展-22c55e?style=for-the-badge" alt="求解器持续扩展"></a>
  <a href="https://github.com/svd-ai-lab/sim-skills"><img src="https://img.shields.io/badge/Agent_Skills-sim--skills-8b5cf6?style=for-the-badge" alt="配套技能"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/许可证-Apache_2.0-eab308?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10--3.12-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/CLI-Click_8-blue" alt="Click">
  <img src="https://img.shields.io/badge/server-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/transport-HTTP%2FJSON-orange" alt="HTTP/JSON">
  <img src="https://img.shields.io/badge/status-alpha-f97316" alt="Status: alpha">
</p>

[English](../README.md) · [Deutsch](README.de.md) · [日本語](README.ja.md) · **中文**

[为什么是 sim](#-为什么是-sim) · [快速开始](#-快速开始) · [演示](#-演示) · [命令](#-命令) · [求解器](#-求解器注册表) · [Skills](https://github.com/svd-ai-lab/sim-skills)

</div>

---

## 🤔 为什么是 sim？

LLM 智能体早已知道怎么写仿真脚本 —— 训练数据里到处都是。它们真正缺的，是一个标准化的方式去**启动一个求解器、一步一步地驱动它、并在每一步之间观察结果**，再决定下一步怎么走。

今天的选项都很糟糕：

- **写完就跑的脚本** —— 智能体写 200 行，整体跑一遍，第 30 行的错误以乱码的形式出现在第 200 行，没有内省、没有恢复。
- **每个求解器一套自定义封装** —— 每个团队都在用不同的形状重复造同一个 launch / exec / inspect / teardown 循环。
- **闭源的厂商胶水** —— 无法组合、没有共同词汇、不会说 HTTP。

`sim` 就是缺失的那一层：

- **一套 CLI**，一套 HTTP 协议，一份**持续扩展的驱动注册表**，覆盖 CFD、多物理场、热分析、前处理、电池建模等等。
- **持久会话** —— 智能体在每一步之间都可以内省。
- **远程优先** —— CLI 客户端和真正的求解器可以位于不同的机器（局域网、Tailscale、HPC 头节点都行）。
- **配套 Agent skills** —— 教大模型如何安全地驱动每一个新后端。

> 容器运行时让 Kubernetes 与容器之间有了标准对话方式；**sim** 让 AI 智能体与工程软件之间也有了。

---

## 🏛 架构

<div align="center">
  <img src="../assets/architecture.svg" alt="sim 架构图：CLI 客户端通过 HTTP/JSON 连接 sim serve（FastAPI），后者持有一个真实的求解器会话" width="900">
</div>

同一套 CLI 的两种执行模式，共享同一个 `DriverProtocol`：

| 模式 | 命令 | 适用场景 |
|---|---|---|
| **持久会话** | `sim serve` + `sim connect / exec / inspect` | 长时间、有状态、需要在每一步之间内省的工作流 |
| **一次性运行** | `sim run script.py --solver X` | 完整脚本作业，希望以编号形式存进 `.sim/runs/` |

完整的 driver 协议、服务器端点、执行管线见 [CLAUDE.md](../CLAUDE.md)。

---

## 🚀 快速开始

> **名字一览：** 仓库 `svd-ai-lab/sim-cli` · PyPI 分发名 `sim-cli-core` · 命令行 `sim` · 导入 `import sim`。是的，三个不同的字符串 —— 仓库名比第一次 PyPI 发布更早；其余的遵循 Python 打包惯例。

前置依赖：[`uv`](https://docs.astral.sh/uv/) —— 安装命令 `curl -LsSf https://astral.sh/uv/install.sh | sh`（macOS / Linux）或 `irm https://astral.sh/uv/install.ps1 | iex`（Windows PowerShell）。国内网络可设 `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`（PowerShell 是 `$env:UV_DEFAULT_INDEX = "..."`）走清华镜像。

**macOS / Linux：**

```bash
# 1. 在装有求解器的机器上，先装 sim 核心 ——
#    此时不用选 SDK：
uv pip install sim-cli-core

# 2. 让 sim 看一眼你的机器，自动选出合适的 SDK profile：
sim check <solver>
# → 报告本机检测到的 solver 安装，以及它们对应的 profile

# 3. 把那个 profile 的 env 启动起来（在 .sim/envs/<profile>/ 创建带固定
#    SDK 的隔离 venv；或者跳过这一步，第 5 步用 --auto-install 让它自动跑）：
sim env install <profile>

# 4. 启动 server（仅当需要跨机访问时才需要）：
sim serve --host 0.0.0.0          # FastAPI，默认端口 7600

# 5. 从智能体 / 你的笔记本 / 网络任意位置：
sim --host <server-ip> connect --solver <solver> --mode solver --ui-mode gui
sim --host <server-ip> inspect session.versions   # ← 总是先做这一步
sim --host <server-ip> exec "solver.settings.mesh.check()"
sim --host <server-ip> screenshot -o shot.png
sim --host <server-ip> disconnect
```

**Windows（PowerShell）：**

```powershell
# 1. 在装有求解器的机器上，先装 sim 核心：
uv pip install sim-cli-core

# 2. 让 sim 看一眼你的机器，自动选出合适的 SDK profile：
sim check <solver>

# 3. 启动 profile env（或第 4 步加 --auto-install 让它自动跑）：
sim env install <profile>

# 4. 启动 server（仅当需要跨机访问时才需要）：
sim serve --host 0.0.0.0          # FastAPI，默认端口 7600

# 5. 从智能体 / 你的笔记本 / 网络任意位置：
sim --host <server-ip> connect --solver <solver> --mode solver --ui-mode gui
sim --host <server-ip> inspect session.versions   # ← 总是先做这一步
sim --host <server-ip> exec "solver.settings.mesh.check()"
sim --host <server-ip> screenshot -o shot.png
sim --host <server-ip> disconnect
```

完整闭环：**检测 → 启动 env → 启动 → 驱动 → 观察 → 收尾** —— 工程师还可以同时盯着求解器 GUI 实时监控。

> **为什么要先 bootstrap？** 每个 `(solver, SDK, driver, skill)` 组合都是
> 独立的兼容性宇宙 —— 不同的 solver 版本可能需要不同的 SDK 版本，而这些
> SDK 版本未必能在同一个 Python env 中共存。sim 把每种组合当成一个隔离的
> "profile env"，于是同一台机器可以同时保留多个版本而不冲突。完整设计在
> [`docs/architecture/version-compat.md`](architecture/version-compat.md)。

---

## 🎬 演示

> 📺 **早期预览：** 一段 agent 驱动真实求解器会话的粗剪版本正在整理中，仍欢迎贡献更精致的录制（见下文）。

> **录制中。** 即将放置一段终端 capture：`sim connect → exec → inspect → screenshot` 驱动一个真实的求解器会话。
>
> 想贡献录制？欢迎使用 [`vhs`](https://github.com/charmbracelet/vhs) 或 [`asciinema`](https://asciinema.org/)，向 `assets/demo.gif` 提 PR。

---

## ✨ 特性

### 🧠 为 Agent 而生
- **持久会话**跨代码片段保持，求解器永不在任务中途重启
- **逐步内省** —— 每次操作之间都可以 `sim inspect`
- **预检 `sim lint`** —— 在启动前抓出缺失的导入和不支持的 API
- **编号运行历史**存于 `.sim/runs/`，通过 `sim logs` 浏览

### 🔌 求解器无关
- **一套协议** (`DriverProtocol`) —— 每个 driver 仅 ~200 行，注册到 `drivers/__init__.py` 即可
- **持久 + 一次性**两种模式共用同一个 CLI
- **开放注册表** —— 新求解器持续加入；CFD、多物理场、热、前处理、电池模型都在范围内
- **配套 skills** 在 [`sim-skills`](https://github.com/svd-ai-lab/sim-skills) —— 让大模型立刻知道每个新后端的坑

### 🌐 远程友好
- **HTTP/JSON 传输** —— 凡是能跑 `httpx` 的地方都能跑
- **客户端 / 服务端分离** —— 智能体在笔记本上、求解器在 HPC 节点、GUI 在工作站
- **Tailscale-ready** —— 为跨网络 mesh 部署而设计

---

## ⚙️ 命令

| 命令 | 功能 | 类比 |
|---|---|---|
| `sim check <solver>` | 检测安装版本并解析 profile | `docker info` |
| `sim env install <profile>` | 启动 profile env（venv + 固定 SDK） | `pyenv install` |
| `sim env list [--catalogue]` | 列出已启动的 env（或全部目录） | `pyenv versions` |
| `sim env remove <profile>` | 销毁一个 profile env | `pyenv uninstall` |
| `sim serve` | 启动 HTTP 服务器（跨机使用时需要） | `ollama serve` |
| `sim connect` | 启动求解器，建立会话 | `docker start` |
| `sim exec` | 在活跃会话中执行 Python 片段 | `docker exec` |
| `sim inspect` | 查询实时会话状态（含 `session.versions`） | `docker inspect` |
| `sim ps` | 显示当前活跃会话与其 profile | `docker ps` |
| `sim screenshot` | 抓取求解器 GUI 截图 | — |
| `sim disconnect` | 关闭会话 | `docker stop` |
| `sim run` | 一次性脚本执行 | `docker run` |
| `sim lint` | 执行前的静态检查 | `ruff check` |
| `sim logs` | 浏览运行历史 | `docker logs` |

所有涉及主机的命令（`check`、`env`、`connect`、`exec`、`inspect`、`disconnect`）都接受 `--host <ip>`，会改为对远程 `sim serve` 执行而不是本机。

环境变量：客户端用 `SIM_HOST`、`SIM_PORT`；运行存储与 profile env 都放在 `SIM_DIR`（默认 `.sim/`）。

### 怎么选 profile

通常不用自己选。`sim check <solver>` 会告诉你已装的 solver 对应哪个 profile，`sim connect ... --auto-install` 会在第一次使用时帮你 bootstrap。逃生口：

- **指定 profile：** `sim connect --solver <solver> --profile <profile>`
- **完全跳过 profile env（旧路径 / 测试）：** `sim connect --solver <solver> --inline`
- **进阶：单 env 直接装：** 把对应的 plugin 包直接装到当前 venv（例如 `pip install <plugin-package>`），跳过 `sim env`。同一台机器只需要一个 solver 版本时合适。

完整设计：[`docs/architecture/version-compat.md`](architecture/version-compat.md)。

---

## 🆚 为什么不直接跑脚本？

| 写完就跑的脚本 | sim |
|---|---|
| 写完整个脚本，运行，祈祷收敛 | 连接 → 执行 → 观察 → 决定下一步 |
| 第 2 步的错误到第 12 步才暴露 | 每一步都先验证再发下一步 |
| 智能体看不见求解器状态 | 每次操作之间都能 `sim inspect` |
| 每次迭代都重启求解器 | 一个持久会话，随心发片段 |
| GUI 对人不可见 | 工程师监控 GUI，智能体后台驱动 |
| 输出解析每个项目都重写 | `driver.parse_output()` 直接给结构化字段 |

---

## 🧪 求解器注册表

驱动注册表是**开放的、有意为之的成长式设计** —— 新增一个后端只需一份 ~200 LOC 的 `DriverProtocol` 实现，加上 `drivers/__init__.py` 里的一行注册，或者作为独立插件包通过 `sim.drivers` entry-point 注册。

内置覆盖范围横跨 CFD、多物理场、电子热分析、隐式与显式结构 FEA、前后处理、网格生成、具身 AI / GPU 物理、分子动力学、优化 / MDAO、电池建模、热物性、电力系统与射频仿真、以及离散事件建模。具体的求解器既可通过内置注册表抵达，也可通过外置插件包接入 —— 参考插件实现见 [`sim-plugin-cantera`](https://github.com/svd-ai-lab/sim-plugin-cantera)。

每个求解器的协议、片段、演示工作流都住在 [`sim-skills`](https://github.com/svd-ai-lab/sim-skills)，它**同样在持续扩展** —— 每加一个新后端就配一份 agent skill。

---

## 🛠 开发

```bash
git clone https://github.com/svd-ai-lab/sim-cli.git
cd sim-cli
uv pip install -e ".[dev]"

pytest -q                       # 单元测试（无需求解器）
pytest -q -m integration        # 集成测试（需要求解器 + sim serve）
ruff check src/sim tests
```

新加 driver 很简单：把 `DriverProtocol` 实现放进 tree 里，或者作为 out-of-tree 插件通过 `sim.drivers` entry-point group 注册。最小 in-tree 参考实现见 `pybamm/driver.py`；插件参考（driver + skill 一起打包）见 [`sim-plugin-cantera`](https://github.com/svd-ai-lab/sim-plugin-cantera)。

---

## 📂 项目结构

```
src/sim/
  cli.py           Click 应用，所有子命令
  server.py        FastAPI 服务（sim serve）
  session.py       connect/exec/inspect 用的 HTTP 客户端
  driver.py        DriverProtocol + 结果数据类
  drivers/
    pybamm/        参考示例：最小一次性 driver
    …              更多 —— 每个已注册的内置后端一个文件夹
    __init__.py    DRIVERS 注册表 —— 新内置后端在这里注册；
                   out-of-tree 插件通过 `sim.drivers` entry-points
                   在运行时被发现
tests/             单元测试 + fixtures + 执行片段
assets/            logo · banner · architecture (SVG)
docs/              翻译版 README（de · ja · zh）
```

---

## 🔗 关联项目

- **[`sim-skills`](https://github.com/svd-ai-lab/sim-skills)** —— 每个支持后端的 agent skills、片段、演示工作流

---

## 📄 许可证

Apache-2.0 —— 见 [LICENSE](../LICENSE)。
