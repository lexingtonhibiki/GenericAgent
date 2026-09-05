# Spec-Driven Development (SDD) SOP

**适用场景**：3步以上、需求模糊、需结构化交付 | **不适用**：1-2步简单任务直接做
**命令入口**：`/specify` → `/plan` → `/tasks` → 现有 plan mode 执行
**模板**：`memory/spec_templates/{spec,plan,tasks}_template.md` —— 执行到对应阶段时 `file_read` 再填充，**平时勿整读**

---

## 项目宪法

> 所有 spec 和 plan 必须通过宪法检查才能进入实施。

| ID | 原则 | 含义 |
|----|------|------|
| P1 | Simplicity First | 最简方案优先，每个抽象必须有 ≥3 个具体用例 |
| P2 | Merge-Friendly | 本地特性自包含于独立文件并标记 [TAG]，不改上游核心文件 |
| P3 | SOP-Driven | 工作流定义在 .md 文件中，代码只负责调度，SOP 变更不需改代码 |
| P4 | Context Efficiency | Agent 上下文是最稀缺资源，重活委托 subagent |
| P5 | Verify Before Declare | 无独立验证不算完成，禁止自我宣布成功 |

**治理**：宪法变更需用户确认；违反项必须记录在 Complexity Tracking 表中。

---

## 工作流总览

```
/specify <描述>    → 产出 spec.md（需求规格）
/plan [技术栈]     → 产出 plan.md（技术计划，含宪法检查）
/tasks             → 产出 tasks.md（结构化任务列表）
(自动进入 plan mode 执行) → 验证 → 完成
```

每阶段产出物存放在 `specs/<NNN>-<短名>/` 目录下。

---

## 阶段一：Specify（需求规格）

**触发**：`/specify <功能描述>` 或用户提出复杂需求时主动进入

### 步骤

1. **创建规格目录**：`mkdir -p specs/<NNN>-<短名>/`
2. **读宪法**：提取上方 P1-P5 原则作为约束
3. **填充 spec 模板**：`file_read memory/spec_templates/spec_template.md`，按其结构创建 `specs/<NNN>-<短名>/spec.md`
4. **质量自检**：
   - 每个用户故事是否有独立测试方法？
   - 功能需求是否可编号追溯（FR-NNN）？
   - `[NEEDS CLARIFICATION]` 是否 ≤3 个？
   - 是否只写了 WHAT/WHY，没写 HOW？
5. **用户确认**：`ask_user` 确认 spec.md 后才能继续

---

## 阶段二：Plan（技术计划）

**触发**：`/plan [技术栈描述]` 或 spec.md 确认后

### 步骤

1. **读 spec.md**：`file_read specs/<NNN>-<短名>/spec.md`
2. **宪法检查（Constitution Check）**：
   - 逐条检查 spec 是否违反 P1-P5 原则
   - 违反项必须记录在 plan.md 的 Complexity Tracking 表中
3. **探索（复用 plan_sop.md 探索态）**：
   - 启动 subagent 探测环境
   - 产出 `research.md`
4. **填充 plan 模板**：`file_read memory/spec_templates/plan_template.md`，按其结构创建 `specs/<NNN>-<短名>/plan.md`
5. **设计产出**（按需）：
   - `data-model.md`：数据模型
   - `contracts/`：接口契约
   - `quickstart.md`：快速上手
6. **二次宪法检查**：设计完成后重新检查
7. **用户确认**：`ask_user` 确认 plan.md

---

## 阶段三：Tasks（任务生成）

**触发**：`/tasks` 或 plan.md 确认后

### 步骤

1. **加载设计文档**：plan.md（必需）+ spec.md（必需）+ data-model.md + contracts/
2. **提取用户故事**：从 spec.md 提取 P1/P2/P3 故事
3. **生成任务**：`file_read memory/spec_templates/tasks_template.md`，按其结构创建 `specs/<NNN>-<短名>/tasks.md`
4. **进入 plan mode**：`code_run({'inline_eval':True, 'script':'handler.enter_plan_mode("specs/<NNN>-<短名>/tasks.md")'})`

---

## 与现有 Plan Mode 的衔接

- `/specify` 和 `/plan` 是 **Plan Mode 的前置增强**，产出结构化文档
- `/tasks` 产出的 tasks.md 可直接作为 plan.md 的执行清单
- 进入执行阶段后，**完全复用现有 plan mode**（enter_plan_mode、验证 subagent 等）
- 无需修改 ga.py 的任何代码

---

## /constitution 命令

**触发**：`/constitution <原则描述>`

1. 读本文件「项目宪法」章节
2. 根据用户输入更新原则
3. 检查所有 specs/ 下的 spec.md 和 plan.md 是否与新原则冲突
4. 产出 Sync Impact Report
