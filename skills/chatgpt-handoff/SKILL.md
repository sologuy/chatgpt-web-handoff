---
name: chatgpt-handoff
description: 把当前任务上下文交接给浏览器里已登录的 ChatGPT Web 做深度审查，取回结构化结论。用法 submit / poll / list / abort
argument-hint: "submit [极速|中级|高级|极高|pro] <要审什么> ｜ poll ｜ list ｜ abort"
user-invocable: true
allowed-tools: Bash
---

# ChatGPT Web Handoff

> 本 Skill 在 Claude Code / Codex / DSH 上行为一致。不依赖任何单一 harness 的模板特性
> （不用参数占位符替换，也不用反引号内嵌 shell 执行）——所有动态信息一律自己跑命令拿。
>
> ⚠️ **这份文档里不能出现那两个模板记号的字面写法**，包括在说明"我们不用它"的句子里。
> Claude Code 会照样处理：内嵌执行记号会被真的执行（跑一个叫 `cmd` 的命令，Skill 直接加载失败），
> 参数占位符会被替换成用户传的参数（正文被改写，且 bash 示例里出现就会被静默替换）。
> 两处都实测过。

## 第 0 步：先摸清状态

```bash
# 哪个 harness 都能用：取第一个存在的路径（两条最终都 symlink 到同一个仓库）
CGH=$(ls "$HOME"/.claude/skills/chatgpt-handoff/cgh "$HOME"/.agents/skills/chatgpt-handoff/cgh 2>/dev/null | head -1)
"$CGH" state
```

没有活跃作业才能建新的。下文 `$CGH` 都指这个路径。

用户这次要什么，看他消息里的原话——**不要从上下文里自己推断审查对象**。

---

## 你只做一件事：写 request.md

浏览器那一整套（开新标签页、校验 host、展开档位菜单、选推理强度、回读档位、
校验模型、注入正文、发送、等真 URL、读进度、判完成、解哨兵）**全部在 `cgh` 里，
是确定性代码，不需要你参与**。不要自己调浏览器工具去做这些事。

你负责的是 `cgh` 做不了的那部分：把当前任务的上下文组织成一份值得对方花算力读的 `request.md`。

---

## submit

### 1. 建作业 —— 用户原话原样传，不要复述

```bash
$CGH new --action <review|design|debug> -- <用户原话>
```

**`--effort` 通常不用传。** `cgh` 会自己从用户原话里认档位，认不出就用默认 `极高`：

| 情况 | 结果 |
|------|------|
| 原话里有档位词（`用 pro 模式` / `极速档` / `中级模式` / `极高`…） | 按原话，`effort_source=用户原话` |
| 原话里没有 | 默认 `极高`，`effort_source=默认` |
| 你显式传了 `--effort` 且原话里没档位词 | 按你传的，`effort_source=显式参数` |
| 你传的 `--effort` 与原话里的档位**不一致** | ❌ `effort_mismatch` 直接拒绝 |

最后一行是关键：**你填的档位会被拿去和用户原话交叉校验**。用户说「用 pro 模式」而你
填了 `high`，`cgh` 会拦住——因为这一路上没有别的东西能发现你听错了（`effort_actual`
照样会回读成"正确的高"）。所以要么别传，要么忠实照抄。

- `--` 之后**原样照抄用户那句话**，不要概括、不要润色、不要translate。
  这句话会被冻结进 `intent.json` 并带哈希，后续任何环节改动它都会被拒绝，
  档位交叉校验也是拿它做的信源。
- 五个档位：`极速` / `中级` / `高级` / `极高` / `pro`。没有 `auto` 这一档。
- 用户没说要审什么 → **停下来问**。不要从对话上下文里自己挑一个题目。
- 返回 `busy` 说明已有活跃作业，把 `active_id` 报给用户，问是 `poll` 还是 `abort`。

**档位按任务难度选，不要为了"省额度"降档。** 用户的 Pro 额度一直没用满过，
额度不是需要你操心的约束。判断标准只有一个：这个问题值不值得更深的推理。
- 架构决策、根因存疑、要对抗性挑刺、上下文很大 → **该上 `pro` 就上 `pro`**，别犹豫
- 事实性核对、格式检查、小范围确认 → 低档就够
不确定时按默认 `极高` 走，也不要因为"怕贵"往下压一档——压错档位拿回一份浅结论，
才是真的浪费（既浪费了这次交接，也浪费了用户等待的时间）。

**用户授权过的档位是持续有效的，不要每轮回头重新请示。**
他说过一次「用 pro」，那这个任务后续的重试、续聊、修完再跑，都还是 pro，
不需要再问「要不要继续用 pro」。反复确认不是谨慎，是把决策推回给用户。
尤其不要写「本次没有消耗额度」这类话来给请示铺垫——
那只在解释失败原因时才有意义，不该变成"所以要不要继续"的引子。

失败重跑同理：`effort_drifted` / `browser_busy` / `attachment_state` 这些都是
工具侧问题，修完直接重跑，不用重新申请授权。

### 2. 填 request.md

编辑 `<dir>/request.md`（`$CGH new` 已渲染好骨架，job_id 与用户原话已填入）。

- 「目标」节里那句用户原话**不要动**，`cgh submit` 会校验它还在不在。
- 「已确认事实」只写有代码 / 日志 / 测试 / 文档支持的内容；「当前分析」明确标为假设。
- git diff 只带相关文件，排除生成物与 lock 文件。
- 尖括号占位符必须全部替换掉，否则 `submit` 会拒绝。
- 不写密钥、内网凭证、患者/客户数据。

### 3. 提交

```bash
$CGH submit --id <job_id>
```

一条命令跑完全流程，返回 `job_id` / `conversation_url` / `effort_actual` / `model_actual`。
**不要等结果**，直接把这几项报给用户。

### 4. 取结果 —— 自己等，不要反复问用户

```bash
$CGH wait --id <job_id> --timeout 1800
```

阻塞到出结果为止，进度打在 stderr。**默认就用这个**，不要每隔几分钟回头问用户"要不要 poll"。

- 返回 `completed`：读 `result.md`，把 `verdict` / `confidence` / `summary` /
  `findings` / `recommended_actions` 复述给用户，附上 `result.md` 路径与对话 URL。
- 返回 `timed_out: true`：**不是失败**，作业还活着。再跑一次 `wait` 接着等。
- 返回 `no_sentinel`：ChatGPT 没按格式收尾，原文已存，交用户判断。

Pro 档实测约 10 分钟，前几分钟 `chars=0` 是正常的思考阶段，不是卡住了。
`wait` 会自己等到底，**这不构成用 Pro 的成本**——你不需要盯着，用户也不需要。

只想看一眼当前进度、不想等，才用 `$CGH poll --id <job_id>`（单次读取，立即返回）。

### 5. 收尾：把这条结论的下场记下来 —— **别跳过这步**

等你把建议落实（或决定不落实）之后：

```bash
$CGH outcome --id <job_id> --status adopted|partial|rejected \
  --commit <落实这条结论的 sha> \
  --note "哪条建议真有用；哪条照做反而是坑"
```

为什么这步不能省：`result.md` 只记录了**对方说了什么**，没有任何地方记录**它说得对不对**。
没有这一条，下次遇到同类问题还是从零判断，这个 skill 永远不会变聪明。

`--note` 要写具体。反例：「有帮助」。正例：
「真金：指出 CDP 断开会收回 override，实测坐实。反面：『自检失败即终止』照字面做会制造故障，
页面刚加载完主线程忙时探针必假阴。」

判断标准：
- `adopted` —— 建议基本照做了
- `partial` —— 部分采纳；**有哪条是坑一定要写进 note**，这是最值钱的信号
- `rejected` —— 没采纳，写清为什么（他判断错了？还是他缺你没给的上下文？）

想看积累到什么程度了：`$CGH stats`（跨仓统计档位性价比、发起方分布、采纳率）。

---

## continue —— 在同一个 ChatGPT 对话里追问

上一轮跑完之后，用户接着问「你说的第 3 点展开讲讲」这类问题，**不要新开会话**：

```bash
$CGH continue --from <上一轮的 job_id> -- <用户原话>
# 然后照常填 request.md，再 $CGH submit --id <新 job_id>
```

- 复用父作业的 ChatGPT 对话，**对方看得见前面聊过的一切**，所以 `request.md`
  的「补充上下文」只写**这一轮新增的信息**，不要重复贴背景。
- 每次追问建一个**子作业**（自己的 job_id / request.md / result.md / 哨兵），
  用 `parent_id` 串成链。这样每一轮的裁决都留得下，不会被下一轮覆盖。
- 档位默认继承父作业；用户原话里点了别的档位就按原话。
- 父作业必须已有 `conversation_url`（即至少提交过一次）。

## 其他命令

```bash
$CGH list                                    # 全部作业（带审查对象与对话 URL，便于回溯）
$CGH state                                   # 当前活跃作业
$CGH poll --id <job_id>                      # 只读一次当前进度，不等待
$CGH doctor [--deep]                         # 开工自检：9222 / ChatGPT 标签页 / 登录态 / 当前档位
$CGH abort --id <job_id> --reason "<原因>"    # 中止并释放并发槽位
$CGH confirm --id <id> --url <对话URL>        # 人工确认「那一发确实发出去了」，补 URL 并推进
$CGH parse --id <id> --from <原文文件>        # 手工兜底：从已保存的原文解析
$CGH outcome --id <id> --status adopted|partial|rejected --note "..."   # 记结论的下场
$CGH stats                                   # 跨仓统计（档位性价比 / 发起方 / 采纳率）
$CGH backfill                                # 把本仓库已有作业补进全机账本（幂等）
```

模型固定 `GPT-5.6 Sol`，每次 submit 都会实测回读。本 Skill 只调推理强度，不切模型。

**并发**：作业闸门是按仓库算的，不同仓库可以同时跑，互不阻塞。
但 ChatGPT 的推理强度是账号级共享偏好，所以 `cgh` 在「设档位 → 发送」这一两秒上加了全机互斥。
偶尔看到 `browser_busy` 或 `effort_drifted`，说明另一个 harness 正好在同一秒提交——
**重跑一次即可，这两种情况都没有发送、不消耗额度**。

---

## 出错怎么办

`cgh` 会自己置状态并把现场留在作业目录里。你只需要把它的报错原样转述给用户，**不要绕路重试**。

| status | 含义 | 该怎么说 |
|--------|------|---------|
| `remote_debug_denied` | 连不上 9222 | 提示 `open -a "Google Chrome" --args --remote-debugging-port=9222`，**不要擅自重启用户的 Chrome** |
| `auth_required` | ChatGPT 未登录 | 请用户在浏览器里登录后重试 |
| `effort_not_found` | 档位标签对不上（通常是界面语言变了） | 把 `effort_available` 里的实际选项列给用户，让他选 |
| `model_changed` | 模型不是钉死的那个 | 报出实测模型名。确认要跟进就改 `bin/cgh_web.py` 的 `EXPECTED_MODEL` |
| `wrong_page` | 目标页不是 chatgpt.com | 直接报告，不要试探 |
| `ui_changed` | 元素定位失败 / 等待超时 | ChatGPT 改版了，报告并停下 |
| `ui_changed` + `background_unfreeze_failed` | 后台标签页解冻失效 | 不是改版。报告 Chrome 版本，别重试——页面已停止渲染，读到的都是旧值 |
| `failed` + `attachment_state` | 输入框里有清不掉的遗留附件，或正文注入没落到 inline/附件任一形态 | **不是改版，也不要重试**。正文超过约 8000 字时 ChatGPT 会转成附件，`cgh` 会自己处理；报这个说明页面状态脏了。让用户看一眼那个标签页的输入框 |
| `send_unknown` | 发送已经打出去了，但没确认到对话 URL | **绝不要直接重跑 submit**，那会产生重复 handoff。请用户去浏览器看那个标签页：<br>真发出去了 → `$CGH confirm --id <id> --url <对话URL>`（要真 id，不要 `/c/WEB:` 开头的临时 id）<br>确实没发出去 → `$CGH submit --id <id> --force-resend` |
| `effort_mismatch` | 你传的 `--effort` 与用户原话里的档位对不上 | **以用户原话为准**。别自己改用户的档位，去掉 `--effort` 让 `cgh` 自己认最省事 |
| `effort_drifted` | 发送前复验发现档位被别的 harness 改走了 | 本次**未发送、不消耗额度**。直接重跑 `submit` 即可 |
| `browser_busy` | 另一个 cgh 正占着「设档位→发送」的临界区 | 同上，重跑即可。一直报就是有进程卡死了 |
| `rate_limited` | 撞额度 | **不自动重投** |
| `inject_mismatch` | 正文粘进去了，但落入的字数与预期对不上 | 报出两个数字。**不要直接重投**——先确认是不是正文里有会被 UI 改写的内容（URL 会被转成 pill、显示时藏掉 scheme+host）。这条报错本身也可能是 cgh 的量法过时了 |
| `no_sentinel` | ChatGPT 没按格式收尾 | 原文已存 `raw-last-message.txt`，交用户判断。**不要自己补字段、不要重跑** |

---

## 硬约束

1. **不要自己开浏览器工具做 handoff**。编排在 `cgh` 里，绕过它就绕过了全部门禁
   （host 白名单、档位回读、模型校验、原话哈希、并发闸门、发送幂等）。
2. **`--force` / `--force-resend` 不要随手加**。前者放行内容检查，后者放行发送闸门。
   加 `--force-resend` 之前必须先让用户确认「上一发真的没出去」——
   加错了会在同一个对话里发出两份一模一样的交接，后续 poll 分不清该认哪一份。
3. **不改写用户原话**。`--` 后面那句是原文，不是让你转述的素材。
4. **不静默降级**。档位/模型对不上一律停下问，不要凑合跑完再交付。
5. **不改写结果**。`result.md` 由 `cgh` 生成，不做"总结的总结"，不删少数派意见。
6. **不碰破坏性控件**。删除对话、清空记忆、改账户设置一律不做。
