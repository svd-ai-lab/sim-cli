# fluent-sim Skill — Natural Language Test Cases (v0)

## Purpose

This dataset is used to validate whether the `fluent-sim` skill is working correctly.
Each case is a natural language prompt that a user might give to an agent.
The goal is NOT to implement the simulation — it is to verify that the agent, guided by the skill, behaves correctly.

**Capabilities under test:**

| Capability | Test focus |
|---|---|
| Task understanding | Does the agent correctly identify workflow type (meshing / solver / full)? |
| Missing-input detection | Does the agent ask for missing info before connecting? |
| Reference usage | Does the agent consult the right reference files when needed? |
| Runtime vs. script mode | Does the agent plan incrementally via `sim run`, not a single end-to-end script? |
| Acceptance-aware completion | Does the agent verify criteria, not just "ran without error"? |

---

## Primary Example: Mixing Elbow (Turbulent Flow + Heat Transfer)

**Source**: `reference/pyfluent_examples/mixing_elbow_settings_api.md`

**Why this example was chosen**:
- Solver-only workflow (no meshing needed — pre-existing `.msh.h5` file)
- Two distinct velocity inlets with different temperatures — tests BC completeness checking
- Uses energy equation + k-epsilon turbulence — tests physics model identification
- Clearly defined material (water-liquid), init method (hybrid), and iteration count
- Well-defined extractable outputs (temperature at outlet, velocity field)
- Already familiar from prior sim demo runs (`exhaust_system` solver workflow)
- Simple enough for early skill validation; complex enough to surface real gaps

---

## Category A — Complete Information Cases

These cases contain all required inputs. Expected behavior: agent forms a concrete runtime execution plan without asking clarifying questions (other than optional confirmation of defaults).

---

### A-01

```yaml
case_id: A-01
source_example: mixing_elbow_settings_api.md
case_type: complete
difficulty: easy
target_workflow: solver
prompt: |
  帮我用 sim 跑一个 mixing elbow 的仿真。网格文件是本地的
  mixing_elbow.msh.h5，路径是 E:\simdata\mixing_elbow.msh.h5。
  流体是水（water-liquid）。冷入口速度 0.4 m/s，温度 20°C，
  热入口速度 1.2 m/s，温度 40°C，液压直径分别是 4 英寸和 1 英寸，
  湍流强度都是 5%。出口是压力出口，回流湍流强度 5%、湍流黏度比 4。
  打开能量方程，用 k-epsilon 模型，hybrid 初始化，跑 150 步。
  任务完成条件是：150 步迭代全部跑完，且出口处平均温度能查到。
missing_fields: []
expected_skill_behavior:
  - 无需追问，直接形成分步 runtime 执行计划
  - 按 runtime_patterns 的 Step Execution Loop 逐步执行
  - 执行完后用 acceptance_checklists 验证：run_count 正确、last.result 中有温度值
  - 不应生成单一端到端脚本
acceptance_focus: 完整信息时能否直接规划并执行 runtime 步骤
```

---

### A-02

```yaml
case_id: A-02
source_example: mixing_elbow_settings_api.md
case_type: complete
difficulty: easy
target_workflow: solver
prompt: |
  I have a mixing elbow mesh file at /home/user/cases/mixing_elbow.msh.h5.
  I want to simulate turbulent water flow with heat transfer.
  Cold inlet: 0.4 m/s at 20°C, hydraulic diameter 4 inches, turbulence intensity 5%.
  Hot inlet: 1.2 m/s at 40°C, hydraulic diameter 1 inch, turbulence intensity 5%.
  Outlet: pressure outlet with backflow turbulent intensity 5% and viscosity ratio 4.
  Material: water-liquid. Enable energy equation. Use realizable k-epsilon.
  Hybrid initialization. Run 150 iterations on 2 processors, no GUI.
  Success: all 150 iterations complete, no negative volumes in mesh check,
  and I can query the average outlet temperature from last.result.
missing_fields: []
expected_skill_behavior:
  - 识别为 solver workflow，sim connect --mode solver
  - 按模板 Template 3 规划步骤顺序（read-case → mesh-check → setup → iterate → extract）
  - 最终验证 run_count 和 last.result.result 中含 outlet_temp
  - 默认值（no_gui, processors=2）明确说明
acceptance_focus: 英文完整输入、明确验收条件时是否直接进入执行
```

---

### A-03

```yaml
case_id: A-03
source_example: mixing_elbow_settings_api.md
case_type: complete
difficulty: medium
target_workflow: solver
prompt: |
  我想验证一个改了边界条件的 mixing elbow 方案。
  网格文件：D:\CFD\mixing_elbow.msh.h5。
  改动：冷入口速度从 0.4 改为 0.6 m/s，温度保持 20°C；
  热入口速度和温度不变（1.2 m/s / 40°C）。
  其余设置（材料、湍流模型、初始化方式）保持默认 water-liquid + realizable k-epsilon + hybrid。
  跑 100 步，要求：迭代完成后报告出口质量加权平均温度（用 report_definitions 提取），
  数值必须在 22°C 到 38°C 之间才算通过。
missing_fields: []
expected_skill_behavior:
  - 识别为 solver workflow with modified BCs
  - 注意到用户给出了明确数值范围作为验收条件（22–38°C）
  - 执行完后不能只说"跑完了"，必须提取数值并与范围比较
  - 参考 reference/pyfluent_examples/mixing_elbow_settings_api.md 中的 report_definitions 用法
acceptance_focus: 数值范围验收条件是否被正确处理（而非仅报告运行成功）
```

---

## Category B — Incomplete Information Cases

These cases deliberately omit key inputs. Expected behavior: agent identifies what is missing and asks the user before proceeding. Agent must NOT assume or fill in values silently.

---

### B-01  缺边界条件

```yaml
case_id: B-01
source_example: mixing_elbow_settings_api.md
case_type: incomplete
difficulty: easy
target_workflow: solver
prompt: |
  帮我跑一个 mixing elbow 的水流仿真，网格文件是 mixing_elbow.msh.h5，
  流体是水，要考虑热传导，用湍流模型，跑 150 步。
missing_fields:
  - cold-inlet 速度和温度
  - hot-inlet 速度和温度
  - 出口类型和出口边界参数
  - 液压直径 / 湍流强度
  - 边界名称是否与网格一致
expected_skill_behavior:
  - 在 connect 之前停下来追问所有缺失的入口边界条件
  - 不得假设速度为某默认值（0.4 m/s 是 example 中的值，不是行业默认值）
  - 应明确告知用户哪些是必填项
  - 可以提示用户参考 mixing_elbow 的标准设置，但不能直接使用它
acceptance_focus: 缺 BC 时是否正确追问，是否不盲目套用 example 中的数值
```

---

### B-02  缺材料与物理模型

```yaml
case_id: B-02
source_example: mixing_elbow_settings_api.md
case_type: incomplete
difficulty: easy
target_workflow: solver
prompt: |
  我有一个弯管的网格文件（elbow_mesh.msh.h5），两个入口一个出口。
  冷入口速度 0.3 m/s，热入口速度 0.9 m/s，出口是压力出口。
  帮我建立仿真并跑 50 步。
missing_fields:
  - 流体材料（空气？水？其他？）
  - 是否需要考虑热传导（能量方程）
  - 湍流模型（或层流？）
  - 入口温度（如果有热传导）
  - 初始化方法
expected_skill_behavior:
  - 识别出流体材料未指定
  - 识别出是否开能量方程不明确（有两个温度不同的入口但用户没说热传导）
  - 识别出湍流模型未说明（Re 数未知，无法自行判断）
  - 应询问这三项，而不是默认使用 water-liquid + k-epsilon
acceptance_focus: 物理模型缺失时是否追问，是否不默认套用 example 设置
```

---

### B-03  缺验收标准

```yaml
case_id: B-03
source_example: mixing_elbow_settings_api.md
case_type: incomplete
difficulty: medium
target_workflow: solver
prompt: |
  请帮我把 mixing elbow 这个算例跑一遍。
  网格文件 mixing_elbow.msh.h5 在 /data/cases/ 下。
  冷入口 0.4 m/s / 20°C，热入口 1.2 m/s / 40°C，
  水，k-epsilon，能量方程，hybrid 初始化，跑 150 步。
  跑完就好。
missing_fields:
  - 没有提供任何验收条件（"跑完就好"不是验收标准）
  - 没有说明需要提取哪些输出值
  - 没有说明如何判断结果可信
expected_skill_behavior:
  - 识别到"跑完就好"不等于任务完成标准
  - 应主动询问：你希望从结果中提取什么量？（温度、质量流量、压降？）
  - 应主动询问：你如何判断这次仿真是成功的？（收敛？迭代完成？数值范围？）
  - 不得在缺乏验收条件的情况下宣布任务完成
  - skill 的 acceptance_checklists 原则：任务完成 ≠ 脚本跑完
acceptance_focus: 无验收条件时 skill 是否拒绝静默完成，并主动追问判据
```

---

### B-04  缺初始化和求解设置

```yaml
case_id: B-04
source_example: mixing_elbow_settings_api.md
case_type: incomplete
difficulty: medium
target_workflow: solver
prompt: |
  我需要跑一个 mixing elbow 算例。
  case 文件已经设置好了，路径是 E:\cases\elbow_configured.cas.h5，
  data 文件是 elbow_configured.dat.h5。
  直接帮我跑迭代就好，我想看收敛结果。
missing_fields:
  - 没有说明迭代步数
  - 没有说明是否需要重新初始化（已有 dat 文件表示可能已初始化）
  - 没有说明判断收敛的标准（残差阈值？固定步数？）
  - 没有说明需要提取哪些结果
expected_skill_behavior:
  - 识别到 dat 文件存在，应先询问：是否从现有场继续迭代，还是重新初始化？
  - 询问迭代步数或收敛条件
  - 询问最终需要提取哪个物理量
  - 不得假设"跑 100 步"或"residual < 1e-3"
acceptance_focus: 有既存 dat 文件时是否正确询问初始化意图，而不是无脑 hybrid_initialize
```

---

### B-05  只给高层目标

```yaml
case_id: B-05
source_example: mixing_elbow_settings_api.md
case_type: incomplete
difficulty: medium
target_workflow: full workflow
prompt: |
  我想仿真一个 T 形管道的混合过程，两股流体在这里混合，
  一股热一股冷，我想看出口温度是多少。帮我完成整个仿真。
missing_fields:
  - 几何文件或网格文件（没有提供任何路径）
  - 流体种类（气体？液体？）
  - 入口速度
  - 入口温度
  - 管道尺寸（影响湍流判断）
  - 是否已有网格或需要先建网格
  - 验收标准
expected_skill_behavior:
  - 不得直接使用 mixing_elbow.msh.h5（那是 example 文件，不是用户文件）
  - 应先澄清是否有现成网格文件
  - 应询问流体种类、速度、温度
  - 如果没有网格，应询问几何文件并提示需要先走 meshing workflow
  - 在所有必要信息确认之前不应进入任何执行规划
acceptance_focus: 高层目标下 skill 是否能正确阻止盲目规划，逐步澄清最小必要信息
```

---

### B-06  信息看似完整但有歧义

```yaml
case_id: B-06
source_example: mixing_elbow_settings_api.md
case_type: incomplete
difficulty: medium
target_workflow: solver
prompt: |
  帮我跑 mixing elbow 案例，用标准设置，迭代到收敛。
missing_fields:
  - "标准设置"语义不明确（example 中的值？用户上次的值？行业默认？）
  - "收敛"没有量化标准（残差值？特定量稳定？）
  - 没有提供文件路径（本地文件还是从 PyFluent example 库下载？）
expected_skill_behavior:
  - 识别"标准设置"是歧义词，不能直接套用 example 中的参数
  - 识别"收敛"需要量化定义
  - 应询问文件来源（本地路径 or PyFluent 内置 example）
  - 不得静默假设任何参数
  - 可以提示用户"我这里有 mixing_elbow 的标准 example 参数，是否使用？"但必须等确认
acceptance_focus: "看似完整"但含歧义时 skill 是否识别并追问，而不是直接执行
```

---

## Category C — Boundary / Stress Cases

These cases test skill behavior at the edges: wrong workflow type, post-processing only, unsupported requests.

---

### C-01  任务超出 v0 范围（后处理）

```yaml
case_id: C-01
source_example: mixing_elbow_settings_api.md
case_type: complete
difficulty: easy
target_workflow: post
prompt: |
  我已经跑完了 mixing elbow 的计算，case 和 data 文件都在
  E:\results\elbow_final.cas.h5 和 elbow_final.dat.h5。
  帮我在 symmetry-xyplane 截面上画出速度矢量图，导出为 PNG。
missing_fields: []
expected_skill_behavior:
  - 识别这是 post-processing 任务
  - 告知用户：后处理可视化导出在 fluent-sim skill v0 中未覆盖
  - 可以指引用户参考 mixing_elbow_settings_api.md 中的 graphics 部分
  - 不得假装能完成并生成一个可能错误的计划
acceptance_focus: v0 范围边界是否被正确识别并诚实告知
```

---

### C-02  launch_fluent 请求的处理

```yaml
case_id: C-02
source_example: mixing_elbow_settings_api.md
case_type: complete
difficulty: medium
target_workflow: solver
prompt: |
  帮我写一个完整的 mixing elbow Python 脚本，从 launch_fluent 开始，
  把所有边界条件设置、初始化、迭代全部写在一个文件里，我自己跑。
missing_fields: []
expected_skill_behavior:
  - 识别用户想要"一个完整脚本"（Style B：single-file workflow）
  - 这是合法的使用方式，不应拒绝或重定向
  - 解释：不能从 launch_fluent 开始，因为 sim 已管理 session；应改用 sim connect + 注入的 solver 对象
  - 提供替代方案：sim connect --mode solver，然后将所有步骤写在一个 sim snippet 里，用 sim run 一次提交
  - 生成的脚本使用注入的 solver 对象，不调用 launch_fluent()
  - 缺少验收标准（"我自己跑"不是验收条件），应询问提取目标
  - 不得生成含 pyfluent.launch_fluent() 的脚本（会启动第二个 Fluent 进程）
acceptance_focus: 正确区分"launch_fluent 不可用"与"单文件脚本不可用"——前者是约束，后者不是
```

---

---

## Category D — Runtime Feedback Cases

These cases provide mid-execution state feedback alongside the initial task. The agent must read the current runtime state, decide whether to continue, adjust, escalate, or stop — NOT blindly resume from where it left off.

Each case adds a `current_state` field representing what `sim query` has returned so far.

---

### D-01  中途步骤失败（ok=false）

```yaml
case_id: D-01
source_example: mixing_elbow_settings_api.md
case_type: runtime_feedback
difficulty: medium
target_workflow: solver
prompt: |
  帮我跑 mixing elbow 的仿真，完整设置如 A-01。
  已经执行了前几步，现在的状态如下，请告诉我下一步怎么做。
current_state: |
  sim query session.summary:
    { "connected": true, "mode": "solver", "run_count": 2 }

  sim query last.result:
    {
      "ok": false,
      "label": "setup-boundary-conditions",
      "stderr": "LookupError: boundary zone 'cold-inlet' is not found at path /setup/boundary_conditions/velocity_inlet",
      "stdout": "",
      "result": null
    }
missing_fields: []
expected_skill_behavior:
  - 不得继续执行下一步（run-iterations）
  - 识别错误原因：boundary zone 名称不匹配
  - 应向用户确认实际的 boundary zone 名称（可能不是 cold-inlet）
  - 建议用户先用 solver.settings.setup.boundary_conditions 查询实际 zone 名称
  - 应参考 runtime_patterns.md Pattern 5（Failure Handling）的行为规范
  - 不得自行猜测正确的 zone 名称并继续执行
acceptance_focus: ok=false 时是否停止、识别根因、向用户确认，而不是盲目继续
```

---

### D-02  run_count 低于预期（某步未执行）

```yaml
case_id: D-02
source_example: mixing_elbow_settings_api.md
case_type: runtime_feedback
difficulty: medium
target_workflow: solver
prompt: |
  我让 sim 跑 mixing elbow 求解任务，预期按照这个顺序执行：
  read-case-data → mesh-check → enable-energy → setup-material →
  setup-bc → hybrid-init → run-iterations
  共 7 步。现在我查了 session 状态，你帮我判断还差什么。
current_state: |
  sim query session.summary:
    { "connected": true, "mode": "solver", "run_count": 4 }

  sim query last.result:
    {
      "ok": true,
      "label": "setup-material",
      "result": { "material": "water-liquid" },
      "stdout": "  material set to water-liquid\n"
    }
missing_fields: []
expected_skill_behavior:
  - 识别 run_count=4，而预期 7 步，说明 steps 5–7 尚未执行
  - 正确推断已完成：read-case-data, mesh-check, enable-energy, setup-material
  - 正确推断待执行：setup-bc, hybrid-init, run-iterations
  - 不得宣布任务完成
  - 应提示用户：当前状态正常，继续执行剩余 3 步
  - 应参考 runtime_patterns.md Pattern 2 的执行顺序和 Pattern 3 的状态查询
acceptance_focus: 通过 run_count 推断 workflow 进度，正确识别"局部已完成，整体未完成"
```

---

### D-03  局部成功 ≠ 整体完成（meshing 场景）

```yaml
case_id: D-03
source_example: exhaust_system_settings_api.md
case_type: runtime_feedback
difficulty: medium
target_workflow: meshing
prompt: |
  我在做 exhaust system 的 fault-tolerant meshing，你来判断当前状态是否完成。
current_state: |
  sim query session.summary:
    { "connected": true, "mode": "meshing", "run_count": 5 }

  sim query last.result:
    {
      "ok": true,
      "label": "generate-surface-mesh",
      "result": { "surface_mesh_done": true },
      "stdout": "  Generate Surface Mesh OK\n"
    }
missing_fields: []
expected_skill_behavior:
  - 识别 surface_mesh_done=true 只是中间步骤成功
  - 识别 volume mesh 尚未生成（result 中没有 volume_mesh_done 字段）
  - 不得宣布 meshing 任务完成
  - 应明确说明：当前状态 = surface mesh 完成，仍需执行 volume mesh 步骤（以及可选的 switch_to_solver）
  - 参照 acceptance_checklists.md Checklist 2 验证逻辑
  - surface_mesh_done=true ≠ volume_mesh_done=true ≠ task complete
acceptance_focus: 中间步骤 ok=true 不能被误判为整体任务完成
```

---

### D-04  迭代跑完但验收未做

```yaml
case_id: D-04
source_example: mixing_elbow_settings_api.md
case_type: runtime_feedback
difficulty: easy
target_workflow: solver
prompt: |
  mixing elbow 仿真已经跑到这个状态，请告诉我任务是否完成。
  原始需求：跑 150 步，完成后提取出口处质量加权平均温度，
  数值在 28°C 到 35°C 之间算通过。
current_state: |
  sim query session.summary:
    { "connected": true, "mode": "solver", "run_count": 5 }

  sim query last.result:
    {
      "ok": true,
      "label": "run-iterations",
      "result": { "iterations_run": 150, "status": "complete" },
      "stdout": "  150 iterations complete\n"
    }
missing_fields: []
expected_skill_behavior:
  - 识别 iterations_run=150，迭代步骤已成功完成
  - 但识别验收条件未满足：出口温度尚未提取
  - 不得宣布任务完成（虽然迭代 ok=true）
  - 应指出：下一步必须执行温度提取步骤（report_definitions.compute），才能验证 28–35°C 范围
  - 参照 acceptance_checklists.md General Rule 1：exit code 0 ≠ 任务完成
  - 参照 acceptance_checklists.md Checklist 3：result extraction 是 [REQUIRED] 项
acceptance_focus: "迭代跑完"≠ 任务完成；提取并验证数值才是 acceptance 的一部分
```

---

## Category E — Workflow Classification Cases

These cases test whether the agent correctly identifies which workflow type is actually needed based on what the user has provided, rather than what they said.

---

### E-01  有几何文件却说"帮我跑仿真"

```yaml
case_id: E-01
source_example: mixing_elbow_settings_api.md
case_type: classification
difficulty: easy
target_workflow: full workflow
prompt: |
  我有一个 mixing elbow 的几何文件（mixing_elbow.pmdb），
  冷入口 0.4 m/s / 20°C，热入口 1.2 m/s / 40°C，水，能量方程，k-epsilon。
  帮我完成整个仿真，跑 150 步，提取出口温度。
missing_fields:
  - 没有网格文件，只有几何文件（.pmdb）
  - 缺 meshing 相关参数（length unit、max size、volume fill 类型等）
expected_skill_behavior:
  - 识别 .pmdb 是几何文件，不是网格文件
  - 不得直接 sim connect --mode solver（没有网格无法 read_case）
  - 应识别需要先走 watertight meshing workflow
  - 应向用户询问 meshing 参数（length unit、surface mesh max size 等）
  - 参照 task_templates.md Template 1 确认缺失项
  - 执行规划必须包含 meshing → solver 两个阶段
acceptance_focus: 文件类型与 workflow 类型的正确分流；不能跳过 meshing 直接 solver
```

---

### E-02  有 cas+dat 却说"帮我完整建模"

```yaml
case_id: E-02
source_example: mixing_elbow_settings_api.md
case_type: classification
difficulty: medium
target_workflow: solver
prompt: |
  这里有 mixing_elbow.cas.h5 和 mixing_elbow.dat.h5，
  帮我完整建模，看看这个弯管的流场是什么样的。
missing_fields:
  - "完整建模"语义不明确
  - 不清楚用户是要重新建模还是在现有场上继续
expected_skill_behavior:
  - 识别 .cas.h5 = 已配置的 case 文件，.dat.h5 = 已初始化的场文件
  - 推断：当前更可能是 solver continuation 或 result extraction，而非重新建模
  - 不得假设需要走 meshing workflow 或重新设置边界条件
  - 应向用户确认意图：是要继续迭代？还是提取当前场的结果？还是从头重新设置？
  - 参照 task_templates.md Template 3（Solver Run）和 B-04 缺初始化意图的处理逻辑
acceptance_focus: 根据已有文件类型推断最可能的 workflow 阶段，而不是照单全收"完整建模"
```

---

### E-03  描述是 meshing 任务但给的是 .msh.h5

```yaml
case_id: E-03
source_example: mixing_elbow_settings_api.md
case_type: classification
difficulty: medium
target_workflow: solver
prompt: |
  我需要对 mixing elbow 做网格划分，文件路径是
  E:\meshes\mixing_elbow.msh.h5，帮我完成网格生成任务。
missing_fields: []
expected_skill_behavior:
  - 识别 .msh.h5 是已完成的网格文件（Fluent mesh format），不是几何文件
  - 识别"做网格划分"与"已有 .msh.h5 文件"之间存在矛盾
  - 应向用户确认：是否已有网格，任务是检查网格质量（mesh check）还是重新生成网格？
  - 如果是 mesh check，下一步是 sim connect --mode solver + mesh.check()
  - 如果是重新生成，需要原始几何文件而不是 .msh.h5
  - 不得直接走 meshing workflow（因为用户没有提供几何文件）
acceptance_focus: 任务描述与文件类型矛盾时，是否识别并追问而不是盲目执行
```

---

## Category F — Reference Routing Cases

These cases test whether the agent selects the correct reference source. Each case has a clear "right answer" for which reference to consult first.

---

### F-01  应该查 example（具体 API 用法）

```yaml
case_id: F-01
source_example: mixing_elbow_settings_api.md
case_type: reference_routing
difficulty: easy
target_workflow: solver
prompt: |
  我在写 mixing elbow 仿真的边界条件设置步骤，
  具体想知道：cold-inlet 的湍流参数（turbulence_specification、
  hydraulic_diameter）在 PyFluent settings API 里是什么路径？
  还有 report_definitions 怎么用来提取出口平均温度？
missing_fields: []
expected_skill_behavior:
  - 识别这是 PyFluent API 用法查询，而不是 runtime 控制问题
  - 应首先查阅 reference/pyfluent_examples/mixing_elbow_settings_api.md
  - 该文件中有完整的 cold_inlet.turbulence.* 路径和 report_definitions 用法
  - 不应查 runtime_patterns.md（与 API 路径无关）
  - 不应查 acceptance_checklists.md（与 API 路径无关）
  - 参考 SKILL.md §7 的索引规则：API lookup → cheat_sheet.md 或 examples
  - 回答时应注明：sim snippet 中不调用 launch_fluent，直接用注入的 solver 对象
reference_should_consult_first: reference/pyfluent_examples/mixing_elbow_settings_api.md
acceptance_focus: 遇到 API 路径查询时，能否正确定位到 example 而不是 runtime 文档
```

---

### F-02  应该查 runtime_patterns（控制流决策）

```yaml
case_id: F-02
source_example: mixing_elbow_settings_api.md
case_type: reference_routing
difficulty: easy
target_workflow: solver
prompt: |
  现在 sim run 返回了 exit code 1，我不知道该怎么处理。
  是应该直接 retry 同一步，还是先 query last.result，
  还是直接 disconnect 报告失败？能告诉我标准做法吗？
missing_fields: []
expected_skill_behavior:
  - 识别这是 runtime 控制流决策，不是 API 用法问题
  - 应首先查阅 reference/runtime_patterns.md Pattern 5（Failure Handling）
  - 标准做法：读 last.result.stderr → 不要 retry → 报告给用户 → 等待指示
  - 不应查 example 文件（与控制流无关）
  - 不应查 acceptance_checklists.md（那是验收判断，不是错误处理）
reference_should_consult_first: reference/runtime_patterns.md
acceptance_focus: 控制流决策问题能否正确路由到 runtime_patterns，而不是 examples
```

---

### F-03  应该查 acceptance_checklists（判断任务状态）

```yaml
case_id: F-03
source_example: mixing_elbow_settings_api.md
case_type: reference_routing
difficulty: medium
target_workflow: solver
prompt: |
  sim query last.result 返回的结果如下，我想知道 mixing elbow
  的 solver 任务是否已经完成，还是需要再做什么：

  {
    "ok": true,
    "label": "run-iterations",
    "result": { "iterations_run": 150, "status": "complete" },
    "stdout": "  150 iterations complete\n"
  }

  session.summary: { "connected": true, "mode": "solver", "run_count": 4 }
missing_fields:
  - 原始验收条件未在此处给出（但用户期望 skill 知道如何判断）
expected_skill_behavior:
  - 识别这是"判断当前任务是否完成"的问题
  - 应首先查阅 reference/acceptance_checklists.md Checklist 3（Solver Run Completion）
  - 根据 checklist 判断：iterations_run=150 满足 [REQUIRED] 迭代完成项
  - 但识别：缺少 result extraction 步骤（是否有 [REQUIRED if extraction requested] 项未完成）
  - 应向用户确认：原始任务是否要求提取具体数值？如果是，任务尚未完成
  - 不应查 examples（与判断完成度无关）
  - 不应查 runtime_patterns（与判断完成度无关）
reference_should_consult_first: reference/acceptance_checklists.md
acceptance_focus: 任务完成度判断问题能否正确路由到 acceptance_checklists
```

---

## Category G — Edge Behavior Cases

These cases test skill behavior under unusual but realistic conditions: contradictory inputs, requests to skip clarification, and explicit output requirements.

---

### G-01  用户输入自相矛盾

```yaml
case_id: G-01
source_example: mixing_elbow_settings_api.md
case_type: contradiction
difficulty: medium
target_workflow: solver
prompt: |
  帮我跑 mixing elbow 仿真。出口设置为压力出口，压力 0 Pa。
  另外出口速度设为 0.5 m/s，确保出口流速均匀。
  冷入口 0.4 m/s / 20°C，热入口 1.2 m/s / 40°C，水，k-epsilon，能量方程，
  hybrid 初始化，跑 150 步。
missing_fields: []
expected_skill_behavior:
  - 识别矛盾：pressure outlet（出口压力边界）和 fixed outlet velocity（速度边界）不能同时成立
  - Fluent 中 pressure outlet 是典型出口类型，不能同时指定出口速度
  - 应向用户说明这两个条件互斥，询问用户实际意图是什么
  - 不得机械照抄两个矛盾条件、生成一个会报错的 snippet
  - 不得静默舍弃其中一个条件
  - 可以建议：如果要控制出口速度，应用 velocity inlet + outlet 倒置，或用 outflow BC
acceptance_focus: 识别物理/设置矛盾，而不是机械执行；追问意图而不是盲目选其一
```

---

### G-02  用户要求"不要追问，直接默认"

```yaml
case_id: G-02
source_example: mixing_elbow_settings_api.md
case_type: boundary
difficulty: hard
target_workflow: solver
prompt: |
  帮我跑 mixing elbow 仿真，缺的参数你自己按标准默认值补全，
  不要问我，直接跑。
  我给的信息：网格文件 mixing_elbow.msh.h5 在 /data/，跑 100 步。
missing_fields:
  - 边界条件（入口速度、温度）
  - 材料
  - 是否开能量方程
  - 湍流模型
  - 初始化方法
  - 验收标准
expected_skill_behavior:
  - 识别用户明确要求"不追问，直接默认"
  - 区分可以合理默认的非关键项 vs. 绝不能静默假设的关键仿真条件
  - 可以默认的：--processors=2, --ui-mode=no_gui, hybrid_initialize
  - 不能静默假设的：入口速度和温度（这是物理条件，不是运行参数）
  - 应告知用户：我可以默认运行参数，但入口速度/温度等物理边界条件我无法替你假设；
    如果你确认用 mixing_elbow example 的标准值（冷入口 0.4 m/s / 20°C，热入口 1.2 m/s / 40°C），请确认
  - 不得在用户未确认物理条件的情况下开始执行
  - 参照 SKILL.md §5 Missing Input Policy 中"必须问"vs"可以默认"的分类
acceptance_focus: 在"不要追问"压力下，skill 是否仍能坚守物理条件必须确认的底线
```

---

### G-03  明确输出物要求

```yaml
case_id: G-03
source_example: mixing_elbow_settings_api.md
case_type: complete
difficulty: easy
target_workflow: solver
prompt: |
  帮我跑 mixing elbow 仿真。
  网格文件 mixing_elbow.msh.h5 在 E:\data\。
  冷入口 0.4 m/s / 20°C，热入口 1.2 m/s / 40°C，
  水，k-epsilon，能量方程，hybrid 初始化，跑 150 步。

  完成后我只要一份简短的数字报告：
  - 出口质量加权平均温度（°C）
  - 冷入口和热入口的质量流量（kg/s）
  - 最终残差值（能量方程和速度方程）

  不需要任何图，不需要 case/data 文件保存。
  只要这三个数字，格式是 JSON，放在 last.result 里。
missing_fields: []
expected_skill_behavior:
  - 识别为完整 solver workflow，信息充分
  - 注意用户明确定义了交付物格式（JSON，三个数字，无图）
  - 在 run-iterations 后，需要执行专门的 extraction 步骤来获取这三个值
  - 最终 last.result 中必须包含 outlet_temp_celsius, cold_inlet_mfr, hot_inlet_mfr, final_residuals
  - 完成判断：这四个字段全部非空才算完成
  - 不得把"迭代完成"当作"任务完成"
  - 参照 acceptance_checklists.md General Rule 3（quote actual value）
acceptance_focus: 输出物要求是否被纳入完成定义；提取步骤是否作为必须执行项而非可选项
```

---

## Summary

| case_id | case_type | difficulty | target_workflow | primary_capability_tested |
|---|---|---|---|---|
| A-01 | complete | easy | solver | 完整信息 → 直接规划执行 |
| A-02 | complete | easy | solver | 英文输入 + 显式验收条件 |
| A-03 | complete | medium | solver | 数值范围验收条件的处理 |
| B-01 | incomplete | easy | solver | 缺边界条件时追问 |
| B-02 | incomplete | easy | solver | 缺材料/物理模型时追问 |
| B-03 | incomplete | medium | solver | 缺验收标准时的行为 |
| B-04 | incomplete | medium | solver | 有既存 dat 文件时的初始化追问 |
| B-05 | incomplete | medium | full workflow | 只有高层目标时的信息澄清 |
| B-06 | incomplete | medium | solver | 歧义"标准设置"的识别 |
| C-01 | complete | easy | post | v0 范围边界告知 |
| C-02 | complete | medium | solver | sim context vs. standalone script |
| D-01 | runtime_feedback | medium | solver | ok=false 时停止并识别根因 |
| D-02 | runtime_feedback | medium | solver | run_count 低于预期时的进度推断 |
| D-03 | runtime_feedback | medium | meshing | 局部成功（surface mesh）≠ 整体完成 |
| D-04 | runtime_feedback | easy | solver | 迭代完成 ≠ 任务完成（缺提取步骤） |
| E-01 | classification | easy | full workflow | 几何文件 → 必须先 meshing |
| E-02 | classification | medium | solver | cas+dat → 不需要重新建模 |
| E-03 | classification | medium | solver | 任务描述与文件类型矛盾时追问 |
| F-01 | reference_routing | easy | solver | API 用法 → 查 example |
| F-02 | reference_routing | easy | solver | 控制流决策 → 查 runtime_patterns |
| F-03 | reference_routing | medium | solver | 完成度判断 → 查 acceptance_checklists |
| G-01 | contradiction | medium | solver | 物理条件互斥时识别并追问 |
| G-02 | boundary | hard | solver | "不要追问"压力下坚守物理条件底线 |
| G-03 | complete | easy | solver | 输出物要求纳入完成定义 |

**Total: 24 cases**

---

## 覆盖度评估

| 能力维度 | 覆盖情况 | 覆盖 case |
|---|---|---|
| Task understanding | ✅ 充分 | A-01~03, E-01~03 |
| Missing-input detection | ✅ 充分 | B-01~06, G-01, G-02 |
| Reference usage routing | ✅ 充分 | F-01~03 |
| Runtime vs. script mode | ✅ 充分 | C-02, A-01~02 |
| Runtime feedback handling | ✅ 充分 | D-01~04 |
| Workflow classification | ✅ 充分 | E-01~03, C-01 |
| Acceptance-aware completion | ✅ 充分 | D-04, G-03, B-03, A-03, F-03 |
| Contradiction / edge behavior | ✅ 有代表性 | G-01~03 |

---

## 剩余缺口（建议 v1/v2 补充）

| 缺口 | 说明 |
|---|---|
| meshing workflow 的 incomplete case | 缺 volume fill 参数、length unit 等 meshing 专属缺失项 |
| 收敛自适应迭代 | 当前 v0 只支持固定步数；"跑到残差 < 1e-4"的逻辑留给 v1 |
| 多步骤连续失败 + 回滚决策 | D-01 只测单步失败；连续失败策略更复杂，v1 覆盖 |
| 并行 / DOE 场景 | `parametric_static_mixer_1.md` 可作为基础，v1 skill 扩展后测试 |
| 跨 session 状态恢复 | 断连后重连，session.summary 是否能正确告知之前状态 |
| 非标准 Fluent 版本兼容性测试 | `DefaultObjectSetting` 类问题，需要专门的版本感知 case |
