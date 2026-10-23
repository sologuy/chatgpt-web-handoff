# chatgpt-web-handoff（`cgh` + `cgimg`）

**用你日常那个 Chrome 里已登录的 ChatGPT Web 做独立审查或生成图片，
把结果取回本地。**

[English](README.md)

[![CI](https://github.com/sologuy/chatgpt-web-handoff/actions/workflows/ci.yml/badge.svg)](https://github.com/sologuy/chatgpt-web-handoff/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-%E2%89%A5%203.9-blue)](#快速开始)
[![deps](https://img.shields.io/badge/dependencies-none-brightgreen)](#快速开始)
[![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](#边界这些得先看)

本地 agent（Claude Code / Codex / DSH…）擅长执行。但遇到根因判断、架构取舍、
出错代价高的改动时，你需要一个**独立视角**——换一个模型、换一套偏见，
而且它对被审的这段代码没有立场。

`cgh` 把当前任务打包成 `request.md`，通过 Chrome DevTools Protocol 驱动你
**那个已经登录着的** ChatGPT 标签页，再把回复解析成带
`verdict` / `findings` / `recommended_actions` 的 `result.md`。

`cgimg` 复用同一套浏览器连接生成图片，支持参考图，并把图片保存到本地。
两个 Skill 可以分别安装；两个 CLI 和共享模块都在这个仓库里。

不装浏览器插件、不用 Native Messaging、不自建 Broker、不另起 Chrome Profile。
全程不读取、不复制、不持久化任何凭证——它用的就是你已经登录好的那个会话。

---

## v0.7.0 · 2026-10-23

- **两个可选 Skill**：同一份仓库可只装 `chatgpt-handoff`、只装 `chatgpt-image-gen`，或两个都装。生图不依赖安装 handoff Skill。
- **共用浏览器代码**：两个 CLI 共用 ChatGPT UI 检查、raw CDP 传输、来源/账本辅助函数，以及覆盖设档位和发送的短时浏览器锁。
- **固定极高档生图**：`cgimg` 支持风格、比例和参考图，等待生成后保存图片，以 JSON 返回路径。
- **保留失败现场**：生图失败保留本次创建的标签页，并在已知时返回页面 ID 和对话 URL。发送未确认时绝不自动重投。

## v0.6.0 · 2026-10-23

`main` 是交付分支：通过验证的改动都会合并并推送到这里。需要固定版本时，使用发布 tag。

- **续聊可追加新附件**：用 `continue --from … --attach …`，继续同一个 ChatGPT 对话。
- **UI 适配与页面恢复**：支持模型回读、中英文档位标签、可见控件定位，以及经核对的未发送草稿恢复；深度自检会回收自身空白页。2026-10-23 真实提交回读为 **GPT-6 / Instant**，同时保留中文档位别名。
- **审查历史留痕**：可识别时记录发起 agent/会话；用 `outcome` 登记采纳决定，追加式账本保留历次更新。
- **统计修正与安全补漏**：`stats --json` 只输出 JSON，按集合差计算已完成但未处置的作业；`backfill --dry-run` 预览缺失事件，`--id` / `--event` 限定补写范围。账本写失败会明确告警，不因此重投 handoff。

本次发布代码通过了 **25 项干跑与真实浏览器提交**，包括故意让账本不可写、再在隔离账本补漏的验证。

## 快速开始

```bash
# 1. 可选装一个或两个 Skill；安装本身不需要 Chrome 或 Node
git clone https://github.com/sologuy/chatgpt-web-handoff.git
cd chatgpt-web-handoff
./scripts/install.sh                    # 只装 handoff，保持原有默认行为
# ./scripts/install.sh --skills image   # 只装生图
# ./scripts/install.sh --skills all     # 两个都装

# 2. 运行任一 CLI 前，Chrome 得开着远程调试端口：
#    （先完全退出 Chrome，再执行）
open -a "Google Chrome" --args --remote-debugging-port=9222     # macOS
# google-chrome --remote-debugging-port=9222                    # Linux

# 3. 在那个 Chrome 里正常登录 chatgpt.com

# 4. 自检
./bin/cgh doctor
```

`install.sh --skills handoff|image|all` 会把选中的 Skill symlink 到
`~/.claude/skills/`、`~/.agents/skills/`、`~/.codex/skills/`；已有 `~/.hermes`
时也会装到 `~/.hermes/skills/`。各 harness 读的是同一份主源。
脚本写入前会检查全部已选目标，遇到实体文件或目录就停止，不覆盖原件，也不删除未选的 Skill。
要隔离安装可设 `CGH_INSTALL_HOME=/path/to/install-root`，它只改变安装根目录。
只要 **Python ≥ 3.9，仅标准库**。不用 pip install，没有构建步骤，不常驻进程。
可选的 `--register-mcp` 需要 Node、npx 和 Claude Code；该 MCP 只用于诊断，
两个 CLI 正常运行都不依赖它。

## 怎么做 handoff

正常入口是 skill，在 Claude Code / Codex / DSH 里直接说：

```
/chatgpt-handoff  审一下上传模块的重试逻辑会不会导致重复扣费
```

也可以自己调 CLI：

```bash
CGH=./bin/cgh

$CGH new --action review -- "审一下重试逻辑会不会导致重复扣费"
$CGH new --action review --attach ./bug.png --attach ./trace.log -- "..."   # 带图片/文件
$EDITOR .chatgpt/web-handoff/<job_id>/request.md    # 把上下文填进去
$CGH submit --id <job_id>                            # 立刻返回，不阻塞
$CGH wait   --id <job_id>                            # 自己等到出结果
$CGH outcome --id <job_id> --status adopted --note "哪条建议真有用、哪条照做是坑"
```

`wait` 会自己轮询——不用有人守着问「好了没」。

续聊时补充文件，或查看、修复账本：

```bash
$CGH continue --from <previous_job_id> --attach ./supplement.pdf -- "请审查新增证据"
# 填新作业的 request.md，再用返回的子作业 job_id 提交并等待结果。
$CGH stats --json
$CGH backfill --dry-run --id <job_id> --event completed
# 核对预览后再执行：
$CGH backfill --id <job_id> --event completed
```

补漏保留原事件时间，不改 job/result 原件，也不推断 outcome。完成事件必须有合法结果块；
原始回答存在时，两者解析结果须一致。重复执行相同补漏不会追加重复事件。

| 命令 | 作用 |
|---|---|
| `new` / `continue` | 建作业 / 在**同一个** ChatGPT 对话里追问，可追加本轮附件 |
| `submit` | 上传附件、选推理档位、注入正文、发送、拿到对话 URL |
| `poll` / `wait` | 读一次进度 / 阻塞到裁决解析完成 |
| `outcome` | 记下建议有没有被采纳——这是唯一能让它进化的信号 |
| `stats` | 跨仓账本统计；`--json` 输出机器可读的汇总和明细 |
| `backfill` | 预览或补写缺失的创建/完成事件；支持 `--dry-run`、`--id`、`--event` |
| `doctor` | 开工自检：端口通不通、登没登录、找不找得到标签页、档位读不读得到 |
| `list` / `state` / `abort` / `confirm` / `parse` | 账本与手工兜底 |

## 怎么生图

使用 `--skills image` 或 `--skills all` 安装后，可以直接调用 Skill：

```
/chatgpt-image-gen  一只橘猫蹲在旧书店的木梯上，午后阳光斜射进来
```

也可以调 CLI：

```bash
./bin/cgimg "一只橘猫蹲在旧书店的木梯上" \
  --style "写实摄影，浅景深" --aspect 3:2 --out ./images

./bin/cgimg "把这个场景画成水彩" --ref ./reference.png --out ./images
```

`cgimg` **固定极高档（xhigh）**，在前台等待生成和保存完成，以 JSON 的 `images[].path`
返回落盘路径。`--ref` 可重复传入；`--note` 追加要求，`--max` 限制保存张数，
`--timeout` / `--interval` 控制等待，`--keep-tab` 让成功后仍保留对话页。
模型会实测回读；`--allow-model-drift` 明确放行预期列表外的模型，但不会降低推理档位。
完整参数见 `./bin/cgimg --help`。

失败会保留本次创建的标签页，并在已知时返回页面 ID 和对话 URL。
**遇到 `send_unknown`、生成超时、下载或保存失败，不要直接重跑：**原请求可能已经在生成，
或已经完成。先查看原对话。成功时默认只关闭本次创建的页，不动其他标签页。
下载不完整时，除已保存路径外还要检查逐图错误。

## handoff 取回来的是什么

`result.md` 存**未经改写的原始回复**，外加解析出的结构化块：

```
verdict: pass | revise | reject
confidence: 0.0-1.0
summary: <一句话结论>
findings: […]
recommended_actions: […]
missing_information: […]
```

不做「总结的总结」，不删少数派意见，不把不确定的结论写成确定的。
如果 ChatGPT 没按格式收尾，你拿到的是 `no_sentinel` 加原文——
**绝不会是模型编出来补上的字段**。

## 它是怎么工作的

```
你的 agent（Claude Code / Codex / DSH / Hermes）
   ├─ chatgpt-handoff → cgh → 仓库里的 request.md / result.md
   └─ chatgpt-image-gen → cgimg → --out 指定的图片文件
        两个 CLI 共用：
        cgh_common.py（来源、账本、浏览器锁）
        cgh_web.py（ChatGPT UI）→ cgh_cdp.py（raw CDP）
             → 127.0.0.1:9222 → 你已登录的 Chrome
```

浏览器那一整套编排在**代码里，不在提示词里**。这是刻意的：二十步带状态转换和分支的流程
本质是状态机，写成提示词就无法断言、无法 diff、无法回归——它不会报错，只会悄悄漂移。
每一步为什么这么写，都在 `bin/cgh_web.py` 的注释里。
Handoff 产物仍落在 `<你的仓库>/.chatgpt/web-handoff/<job_id>/`。

## handoff 的代码保证

下面每条都是代码里在查的，不是文档里许的愿：

- **档位不静默降级。** 请求的推理档位在 UI 里找不到，作业停在 `effort_not_found`
  并列出实际可选项，绝不会悄悄用低档跑完再把结果交给你。
- **档位设完要回读**，发送前再复验一次——推理档位是账号级偏好，
  另一个标签页随时可能把它改掉。
- **模型是实测回读的**，不是假设的（用 `CGH_EXPECTED_MODEL` 钉你自己的）。
- **页面白名单。** 任何点击前先确认 host 属于 `chatgpt.com` 或 `chat.openai.com`。
- **发送幂等。** 发出去了但对话 URL 没出现，会置 `send_unknown`——
  非终态，且拒绝自动重投。
- **你的原话被 sha256 冻结**并交叉校验，agent 改不了你要审什么，
  也换不掉你点名的档位。
- **产物在你仓库里默认 gitignore**——`request.md` 里装的是你的代码。

## 边界，这些得先看

- **在 macOS 上开发**。Linux 理论上能跑（代码路径里没有 macOS 专属的东西），但没实测过。
- **和 UI 耦合。** ChatGPT 会改版。改坏了某个锚点时你拿到的是 `ui_changed` 加现场快照，
  **不是一个错的答案**。修法是改 `bin/cgh_web.py`，代码注释写清了每个锚点是什么、为什么。
- **档位标签只匹配中英文。** 其他界面语言会明确失败在 `effort_not_found` 并列出实际看到的
  标签，把你的加进 `EFFORT_LABELS` 即可。
- **不写单元测试。** 这里的验证靠真跑——干跑测不出浏览器那一半。
  改动 `bin/` 后须真跑低档位 handoff 和生图，并包含带参考图的验证。
- **每个仓库同时只跑一个 handoff 作业**，用 lockfile 实拦。两个 CLI 共用
  `~/.cgh/browser.lock`，只锁设档位、模型/档位复验、发送与确认；上传、生成和下载都在锁外。
  这不提供批量运行或并发调度能力。
- **这是个人的、本地的、低频的工具。** 它不是 ChatGPT API 的替代品，不是共享服务，
  不做批量。自动化操作 Web 会话与服务条款的关系需要你自己判断，后果也由你承担。

## 参与贡献

见 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md) —— ChatGPT 改版把东西弄坏了、
或者想加你的界面语言，从那里开始。

## 许可

MIT，见 [LICENSE](LICENSE)。
