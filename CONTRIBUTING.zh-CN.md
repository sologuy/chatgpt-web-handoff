# 参与贡献

[English](CONTRIBUTING.md)

你来这儿最可能的原因：**ChatGPT 改版了，某个地方坏了。** 所以先讲这个。

## 修一个失效的锚点

UI 改版把东西弄坏时，`cgh` 会明确失败——`ui_changed`、`effort_not_found`
或 `attachment_state`——并保留现场。**它不会返回一个错的答案。**
这是刻意设计的，你打补丁时请保持这一点。

1. 复现：先 `./bin/cgh doctor`，再用低档位真跑一次 `submit`。
2. 读 `bin/cgh_web.py`。每个锚点都有注释写清它是什么、为什么这么写——
   那些注释大多是某个 bug 留下的疤，动手前先读。
3. 元素定位优先级，**不许跳级**：
   1. a11y role + accessible name
   2. 页面可见文本
   3. `data-testid` / `data-message-author-role`
   4. 放弃：保存快照，置 `ui_changed`
   禁止写死 CSS selector 路径，禁止凭坐标盲点。
4. **保持失败是响的。** 如果你发现自己在加一个「让流程在状态不明时继续走下去」的兜底，
   那你正在制造的，恰恰是这个工具存在的理由所要防的那类缺陷。

## 加你的界面语言

有两处和语言耦合，都在 `bin/cgh_web.py`：

```python
EFFORT_LABELS = {"instant": ["极速", "Instant"], ...}   # 推理档位名
/在文本字段中显示|Show in text field/                    # 超长粘贴转成的附件 chip
```

两处都加上你的标签。档位标签对不上时 `cgh` 会停在 `effort_not_found`
并打印它实际看到的选项——把那个列表贴进 PR 里。

## 怎么验证改动

**本项目不写单元测试，这是刻意的。** 这个程序有一半活在别人控制的浏览器里；
对那一半做 mock 测试，测的是你的假设，不是现实。真正有效的是：

```bash
./scripts/dryrun.sh          # 25 项检查，不需要浏览器；CI 跑的也是这个
```

`dryrun.sh` 覆盖账本、锁、状态机、档位识别、哨兵解析、内容门禁。
它**测不到**开标签页、设档位、注入正文、发送、判完成。

所以全绿之后还得：

```bash
./bin/cgh new --action review -- "<一个小问题，用你自己的话>"
# 填 request.md
./bin/cgh submit --id <job_id> && ./bin/cgh wait --id <job_id>
```

在 PR 里说明你真跑过、用的哪个档位。**动了 `bin/` 却只做了干跑的 PR 不算验证过**，
会被按未验证处理。

## 分层边界

| 文件 | 负责 | 不能做 |
|---|---|---|
| `bin/cgh_cdp.py` | WebSocket 传输、通用页面操作 | 知道任何 ChatGPT 的事 |
| `bin/cgh_web.py` | ChatGPT 语义：标签页、档位、注入、进度 | 管作业账本 |
| `bin/cgh` | 作业、锁、状态机、解析、CLI | 直接驱动浏览器 |

`cgh_cdp.py` 刻意不做成通用 DevTools 框架，别把它养成那样。

## 硬规矩

改 `bin/` 里任何东西之前先读 `AGENTS.md` §6。PR 不得：

- 读取、记录或持久化任何凭证——一次都不行。
- 在 host 不属于 `chatgpt.com` / `chat.openai.com` 的页面上做操作。
- 静默降到更低的推理档位。
- 在发送未确认的情况下自动重投。
- 改写、概括或「整理」ChatGPT 的输出。
- 引入第三方依赖。只用标准库，Python ≥ 3.9。CI 会拦。

## 明确不做

多账号、批量运行、并发调度、托管服务、浏览器插件、ChatGPT API 替代品。
这是个人的、本地的、低频的工具，会一直是。

## commit 与 PR

格式：`<type>: <中文摘要>`，type ∈ `feat` / `fix` / `docs` / `chore` / `design`。

正文写**为什么**，不只是写做了什么——某个锚点、某个阈值背后的理由，
只有 commit log 里还留得住。推之前跑 `git status --short`，
确认没有凭证、没有 `.env`、没有 `.chatgpt/web-handoff/` 作业产物。
