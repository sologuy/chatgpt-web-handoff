# chatgpt-web-handoff（`cgh`）

**把编码 agent 手上这个任务的上下文，交接给你日常那个 Chrome 里已登录的 ChatGPT Web，
再把结构化裁决取回本地仓库。**

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

不装浏览器插件、不用 Native Messaging、不自建 Broker、不另起 Chrome Profile。
全程不读取、不复制、不持久化任何凭证——它用的就是你已经登录好的那个会话。

---

## 快速开始

```bash
# 1. Chrome 得开着远程调试端口。如果还没开：
#    （先完全退出 Chrome，再执行）
open -a "Google Chrome" --args --remote-debugging-port=9222     # macOS
# google-chrome --remote-debugging-port=9222                    # Linux

# 2. 在那个 Chrome 里正常登录 chatgpt.com

# 3. 安装
git clone https://github.com/sologuy/chatgpt-web-handoff.git
cd chatgpt-web-handoff
./scripts/install.sh

# 4. 自检
./bin/cgh doctor
```

`install.sh` 会把 skill symlink 到 `~/.claude/skills/`、`~/.agents/skills/`、
`~/.codex/skills/`，Claude Code / Codex / DSH 三端读的是同一份。
只要 **Python ≥ 3.9，仅标准库**。不用 pip install，没有构建步骤，不常驻进程。

## 怎么用

正常入口是 skill，在 Claude Code / Codex / DSH 里直接说：

```
/chatgpt-handoff  审一下上传模块的重试逻辑会不会导致重复扣费
```

也可以自己调 CLI：

```bash
CGH=./bin/cgh

$CGH new --action review -- "审一下重试逻辑会不会导致重复扣费"
$EDITOR .chatgpt/web-handoff/<job_id>/request.md    # 把上下文填进去
$CGH submit --id <job_id>                            # 立刻返回，不阻塞
$CGH wait   --id <job_id>                            # 自己等到出结果
$CGH outcome --id <job_id> --status adopted --note "哪条建议真有用、哪条照做是坑"
```

`wait` 会自己轮询——不用有人守着问「好了没」。

| 命令 | 作用 |
|---|---|
| `new` / `continue` | 建作业 / 在**同一个** ChatGPT 对话里追问 |
| `submit` | 选推理档位、注入正文、发送、拿到对话 URL |
| `poll` / `wait` | 读一次进度 / 阻塞到裁决解析完成 |
| `outcome` | 记下建议有没有被采纳——这是唯一能让它进化的信号 |
| `stats` | 跨仓统计：档位性价比、发起方分布、采纳率 |
| `doctor` | 开工自检：端口通不通、登没登录、找不找得到标签页、档位读不读得到 |
| `list` / `state` / `abort` / `confirm` / `parse` | 账本与手工兜底 |

## 取回来的是什么

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
你的 agent（Claude Code / Codex / DSH）
   └─ skill：只负责写 request.md，别的什么都不干
        └─ cgh（确定性：作业账本、锁、档位控制、结果解析）
             └─ 裸 CDP → 127.0.0.1:9222
                  └─ 你日常那个 Chrome，ChatGPT 已登录
                       └─ 产物落在 <你的仓库>/.chatgpt/web-handoff/<job_id>/
```

浏览器那一整套编排在**代码里，不在提示词里**。这是刻意的：二十步带状态转换和分支的流程
本质是状态机，写成提示词就无法断言、无法 diff、无法回归——它不会报错，只会悄悄漂移。
每一步为什么这么写，都在 `bin/cgh_web.py` 的注释里。

## 真正被代码执行的保证

下面每条都是代码里在查的，不是文档里许的愿：

- **档位不静默降级。** 请求的推理档位在 UI 里找不到，作业停在 `effort_not_found`
  并列出实际可选项，绝不会悄悄用低档跑完再把结果交给你。
- **档位设完要回读**，发送前再复验一次——推理档位是账号级偏好，
  另一个标签页随时可能把它改掉。
- **模型是实测回读的**，不是假设的（用 `CGH_EXPECTED_MODEL` 钉你自己的）。
- **页面白名单。** 任何点击前先确认 host 属于 `chatgpt.com`。
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
  改完重跑一次真实的低档位作业。
- **每个仓库同时只跑一个作业**，用 lockfile 实拦。不同仓库并行互不阻塞；
  全机互斥只锁「设档位 → 发送」那一两秒。
- **这是个人的、本地的、低频的工具。** 它不是 ChatGPT API 的替代品，不是共享服务，
  不做批量。自动化操作 Web 会话与服务条款的关系需要你自己判断，后果也由你承担。

## 参与贡献

见 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md) —— ChatGPT 改版把东西弄坏了、
或者想加你的界面语言，从那里开始。

## 许可

MIT，见 [LICENSE](LICENSE)。
