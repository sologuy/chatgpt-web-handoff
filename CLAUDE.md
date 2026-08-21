@AGENTS.md

# CLAUDE.md —— Claude Code 专用补充

项目规则统一在 `AGENTS.md`（Claude Code / Codex / DSH 共用），已由上面的 `@AGENTS.md` 导入。
**本文件只放 Claude Code 专用内容；新增或修改项目规则请写进 `AGENTS.md`。**

## 浏览器通道

正常 handoff 一律走 `cgh submit` / `cgh poll`，它们用自有 raw CDP 连 `127.0.0.1:9222`。

**不要自己调 `mcp__chrome-devtools__*` 去做 handoff** —— 那会绕过 host 白名单、档位回读、
模型校验、原话哈希、发送幂等这一整套门禁。MCP 只在 ChatGPT 改版后重新摸底 DOM 时用
（它的 a11y 快照会正确隐藏被 `overflow:clip` 裁掉的节点，裸 DOM 不会）。

⚠️ **不要用 Playwright（MCP 或 Python）连本机 9222 的 Chrome**：旧版 `connectOverCDP()`
会替换 Chrome 的下载委托，下载文件变成无扩展名的 `playwright-artifacts-*`，
断开或杀进程都不恢复，只能重启 Chrome。跑 handoff 时也不要同时挂 claude-in-chrome，
两个自动化通道会互抢标签页和焦点。

## 上下文纪律

轮询 ChatGPT 生成状态用 `evaluate_script` 取最后一条 assistant 消息的尾部文本，
**不要用 `take_snapshot`** —— 长对话的完整 a11y 树会把上下文吃光。
快照只在定位控件和失败留证时用。

## 这个 Chrome 是用户日常在用的

任何交互前先校验目标页 host ∈ `chatgpt.com`；不要对无关标签页做快照、执行脚本或读网络请求。
开新标签页做实验，用完关掉，不要动用户已有的对话页。

**不要替用户点「发送」以外的破坏性按钮**：删除对话、清空记忆、修改账户设置一律不碰；
遇到会弹 `confirm` / `alert` 的元素先停下问。

## Skill 真相源在仓库

`skills/chatgpt-handoff/SKILL.md` 是真相源，`scripts/install.sh` 已把它 symlink 到
`~/.claude/skills/chatgpt-handoff`。不要直接改 `~/.claude/skills/` 下的路径（那就是本仓库）。

## MCP 注册（可选，仅用于改版摸底）

Skill 要在任意项目里可用，所以 scope 必须是 user：

```bash
claude mcp add chrome-devtools -s user -- \
  npx -y chrome-devtools-mcp@1.7.0 --browserUrl http://127.0.0.1:9222 \
  --no-usage-statistics --no-performance-crux \
  --no-category-performance --no-category-network --no-category-emulation \
  --screenshotFormat webp --screenshotMaxWidth 1280
```
