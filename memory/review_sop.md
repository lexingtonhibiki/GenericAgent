# Review Mode SOP

> In-session adversarial code reviewer。用 `/review` 触发,主 agent 在当前对话内
> 拉起评审,报告直接 echo 到对话,**不开 subagent / 不落盘 / 不打 sentinel**。

## 一、何时使用

- 用户输入 `/review` 命令,或自然语言要求 "code review" 时启用
- 典型用例:作者刚写完一段代码 → `/review` 对自己的改动做对抗性 review

## 二、快速启动

| 命令 | 行为 |
|---|---|
| `/review` | 默认审本次 uncommitted 改动(主 agent 跑 `git diff --stat HEAD` + `git diff HEAD`) |
| `/review <自然语言请求>` | 按描述的范围去审(可指定文件 / 目录 / 任务) |
| `/review help` | 显示用法 |

**非 git 仓库**:主 agent 提示用户在下一句 `/review` 塞入具体路径或范围,本轮结束。

## 三、入口链(执行协议唯一源)

```
任意前端 (TUI / Streamlit / wechat / desktop)
   └─ frontends/review_cmd.py     ← install() 接管 /review; _render_prompt() 注入 {user_request} + {ga_root}
       └─ memory/review_sop/review_inline_prompt.txt   ← 完整 in-session 协议
           └─ memory/code_review_principles.md         ← 15 条好代码原则(每条 finding 必须映射到其中一条)
```

`review_inline_prompt.txt` 是唯一执行协议源,内含:三条铁律(Review-only 只读 / Challenge the approach / 报告输出完即结束)、5 步工作流、Q1-Q4 对抗性 framing、P0-P3 Severity 与 Verdict 决议、防误报八规则、措辞八规范、输出协议(整段 echo,不落盘)。

**本文件只是入口说明——执行细节一律以 `review_inline_prompt.txt` 为准,两边禁止重复维护。**

## 四、扩展点

- **自定义评审条目**:编辑 `memory/code_review_principles.md`,reviewer 启动时整段注入
- **触发更换**:要把 `/review` 改成别的命令,只动 `frontends/review_cmd.py` 的 `install()` 一处
