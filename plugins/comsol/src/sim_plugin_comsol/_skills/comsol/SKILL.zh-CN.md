---
name: comsol-sim
description: 当用户需要处理 COMSOL Multiphysics 任务时使用：通过 sim CLI 构建、调试、求解或检查 `.mph` 模型。覆盖 JPype Java API session、shared-desktop GUI 协作、离线 `.mph` 检查，以及非常有限的 Desktop attach 回退。优先使用 `sim connect --solver comsol`，不要直接调用原始 COMSOL API。
---

# COMSOL via sim CLI

这个 skill 教 Agent 如何通过本机 `sim` CLI 驱动 **COMSOL Multiphysics**。
WorkBuddy / CodeBuddy / Claude Code 等 host 通用，流程一致。

## 第一次操作前的检查

如果不确定用户是否已经装好 sim + COMSOL driver，先运行：

```powershell
sim --version              # 确认 sim CLI 在 PATH 上
sim plugin list            # 查看当前环境注册的 plugin
sim plugin info comsol     # 查看 COMSOL plugin 元信息
sim plugin doctor comsol   # 检查 plugin entry point / skills / metadata
sim check comsol           # 检查 COMSOL driver 和本机 COMSOL 安装
```

如果 `sim --version` 失败，让用户重装或确认 PATH 配置，或直接运行：

```powershell
uv tool install sim-cli-core --with sim-plugin-comsol --upgrade --force
```

如果 `sim check comsol` 报告 COMSOL driver 不存在，说明提供 `sim` 的 Python 环境
里没有 `sim-plugin-comsol`。推荐使用 uv 全局工具环境(上面的 `uv tool install ... --with`
命令)；普通 uv 项目则使用：

```powershell
uv add sim-cli-core sim-plugin-comsol
uv run sim plugin sync-skills --target .agents/skills --copy
```

如果 plugin 存在但没有检测到本机 COMSOL，说明用户没有安装 COMSOL Multiphysics，
或当前进程无法访问它。不要尝试 live solve；可以改用已保存 `.mph` 文件检查。

## 控制路径选择

| Path | 适合 | 避免用于 |
|---|---|---|
| `sim connect --solver comsol` | 默认路径。建模、求解、检查、保存 `.mph`、可复现 workflow。 | 极少需要避免。 |
| `sim connect --solver comsol --ui-mode gui --driver-option visual_mode=shared-desktop` | 同上，并且用户想看 Model Builder tree 实时更新。 | Headless / unattended run。 |
| Saved `.mph` inspection | 离线总结、查看文件里有什么、比较 `.mph`。 | 修改 live model。 |
| Desktop attach / Java Shell | 只在用户明确要求对已打开的普通 COMSOL Desktop 做很小修改时作为脆弱回退。 | 默认自动化、长流程、需要结构化异常和验证的工作。 |
| `comsolcompile` + `comsolbatch` | 沙盒 one-shot Java workflow。 | 有状态或交互式工作；能用 sim runtime 时优先用 sim runtime。 |

## 必须遵守的工作协议

把 COMSOL 当成一个有状态的 Java model tree，不要当成一次性代码生成器。很多
`set(...)` 调用会改变 model，但下游对象要等相关 sequence build/run 后才刷新。
需要下游状态时，把 `run()` 当作有意的同步点，而不是机械地每行之后都 run。

1. 如果用户只是问一个已保存 `.mph` 里有什么，优先用离线 `.mph` 检查，不需要
   `sim connect`。
2. live work 先选控制路径，再运行 `sim check comsol`，然后
   `sim connect --solver comsol [--ui-mode gui ...]`。
3. 修改 model 前，先建立身份和 workdir：根据 case name 设 model tag，尽早保存
   `.mph` 到绝对路径，把文件放在 `<workdir>/{model,input,output,scripts,logs}/`。
4. 动手前检查 baseline：`sim inspect session.health` 和
   `sim inspect comsol.model.describe_text`。
5. 一次只执行一个有边界的建模步骤：geometry、materials、physics、mesh、study、
   results 分层推进。不要写 200 行 monolithic builder。
6. 每一步后检查：`sim inspect last.result` 和
   `sim inspect comsol.node.properties:<tag>`。每个 major layer 后保存 checkpoint
   `.mph`，例如 `<case>_01_geometry.mph`。
7. 只有 live model 和用户意图一致后才继续。

## COMSOL 硬约束

1. **不要在 snippet 里调用 `mph.start()` 或 `client.create()`。**
   sim CLI 已经启动 COMSOL JVM 并绑定 `model` handle；第二次 start 会产生冲突。
2. **Windows 上 JPype 路径的图片导出不可靠。** 优先使用 `EvalGlobal`、
   `EvalPoint`、Numeric probe 或 CSV 数据导出，不要依赖
   `model.result().export()` PNG。
3. **设置属性前先检查 live node。** 优先用
   `sim inspect comsol.node.properties:<tag-or-dot-path>`，不要猜 property name。
4. **不要运行超长 monolithic builder。** 分层构建、检查、保存。
5. `comsolcompile` 路径下，Java 代码必须使用 chain-style：
   `model.X("tag").Y("tag2")...`。不存在公开的 `Component`、`Geometry`、
   `HeatTransfer` 等类型；写 `Component c = ...` 会编译失败。

## 已保存 `.mph` 离线检查

对于“这个 `.mph` 文件里有什么？”这类问题，优先用 stdlib reader，不要启动 COMSOL：

```python
from sim_plugin_comsol.lib import inspect_mph
summary = inspect_mph("path/to/case.mph")
```

`MphArchive` 和 `mph_diff` 也可用。这条路径不需要 COMSOL license。

## live session introspection

`sim connect --solver comsol` 后，常用检查目标：

```powershell
sim inspect session.health
sim inspect session.versions
sim inspect last.result
sim inspect comsol.model.identity
sim inspect comsol.model.describe_text
sim inspect comsol.node.properties:<dot-path>
```

如果 `checkpoint_ready: false`、缺少 `file_path`，或 bound tag 和
`active_model_tag` 不一致，把它当成 pause-and-repair 状态，先修复 model 身份和
checkpoint，再继续建模。

## shared-desktop GUI 模式

当用户想看 Model Builder tree 随 Agent 操作实时更新时：

```powershell
sim connect --solver comsol --ui-mode gui --driver-option visual_mode=shared-desktop
sim inspect session.health
```

确认 `effective_ui_mode: shared-desktop`、
`ui_capabilities.model_builder_live: true`，并确认 `active_model_tag` 就是后续
snippet 会修改的 model。如果 `model_builder_live: false`，Desktop 和 JPype 没有
同步，先修复，不要继续假设 GUI 看到的是 agent 正在改的模型。

## attach-only external server

如果用户希望一个 COMSOL server 跨多个 sim session 存活，先在 Windows shell 中启动
外部 server：

```powershell
comsolmphserver.exe -port 2036 -multi on -login auto -silent
```

然后用 sim attach：

```powershell
sim connect --solver comsol --ui-mode gui `
  --driver-option attach_only=true `
  --driver-option port=2036 `
  --driver-option visual_mode=shared-desktop
```

attach-only 模式下，`session.health` 应显示 `server_owner: "external"` 和
`attach_only: true`。`sim disconnect` 会释放 JPype client 和 plugin 启动的 Desktop，
但不会杀掉外部 `comsolmphserver`。

## 脆弱回退：Desktop attach / Java Shell

正常 COMSOL 工作不要使用这条路径。只有用户明确要求在已经打开的普通 COMSOL
Desktop 里做非常小的修改，并拒绝 server-backed `shared-desktop` 路径时才考虑。

```powershell
uvx --from sim-plugin-comsol sim-comsol-attach open --json --timeout 120
uvx --from sim-plugin-comsol sim-comsol-attach health --json
uvx --from sim-plugin-comsol sim-comsol-attach exec --file step.java --submit-key ctrl_enter --json
```

注意：

- COMSOL 6.4 Desktop 标题可能是 `Untitled.mph - COMSOL Multiphysics`，窗口匹配要
  用 substring，不要只匹配 prefix。
- 使用 `--submit-key ctrl_enter`。点击 Run 按钮可能只粘贴代码，不一定执行。
- Java Shell 里不一定有当前 `model` / `m` 变量，先用很小的
  `System.out.println(...)` probe。
- Java Shell 写文件可能被 COMSOL Security preference 拒绝；可用 in-model table，
  或让用户显式允许文件访问。

## 常见对话框

- **"连接到 COMSOL Multiphysics Server"** / **"Connect to COMSOL
  Multiphysics Server"** 可能只是 stale/separate Desktop login dialog，不证明
  JPype server session 失败。先看 `sim inspect session.health`。
- **"是否保存更改?"** / **"Save changes?"** 通常是单独打开的 `.mph` 有未保存修改。
  按用户意图选择 Save 或 Don't Save。

## 截图责任

如果 host (WorkBuddy / CodeBuddy / Claude Code 等) 能看到用户桌面，优先用宿主自己
的截图能力；它看到的就是用户看到的画面。只有 solver GUI 在远程机器上、本地 Agent
不能直接截图时，才使用 `sim screenshot`。

## 工作目录约定

```text
<workdir>/
  model/<case_slug>.mph
  model/<case_slug>_01_geometry.mph
  model/<case_slug>_02_materials.mph
  model/<case_slug>_03_solved.mph
  input/
  output/
  scripts/
  logs/
```

涉及外部文件时，设置 `model.modelPath(...)` 指向相关 `input/` 和 `model/` 目录。
保存、导出、log path 优先使用绝对路径。

## 卡住时

1. 先看 `sim inspect session.health`：常见问题是 `model_builder_live: false`、
   JPype disconnected，或 stale Desktop dialog 阻塞 server。
2. 再看 `sim inspect last.result`：这里有最近一次 `sim exec` 的异常和 workdir 状态。
3. Java compile error 常见原因是用了不存在的 typed variable；改成 chain-style。
4. Windows image export 失败时，改用 numeric probe + CSV export，再用 Python 画图。

## Reference

完整参考随 `sim-plugin-comsol` Python package 分发。普通 uv project 可先同步 skill：

```powershell
uv run sim plugin sync-skills --target .agents/skills --copy
```

公开源码里的参考文档：
https://github.com/svd-ai-lab/sim-plugin-comsol/tree/main/src/sim_plugin_comsol/_skills/comsol/base/reference

常用文件：

| File | 何时阅读 |
|---|---|
| `runtime_introspection.md` | 构建新的 inspect target 或解释 inspect result |
| `java_api_patterns.md` | 写 live JPype snippet：tags、properties、selections |
| `java_batch_patterns.md` | 写 `.java` 给 `comsolcompile`：chain-style 规则和反模式 |
| `mph_file_format.md` | `.mph` archive 结构、`nodeType` 变体、T-parameter contract |
