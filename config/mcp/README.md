# MCP 配置

只有一份配置：**复用你日常那个 Chrome（已在 9222 开着远程调试、免授权）**。

参数已按 `chrome-devtools-mcp@1.7.0` 实测核对。

## 注册（scope 必须是 user）

```bash
claude mcp add chrome-devtools -s user -- \
  npx -y chrome-devtools-mcp@1.7.0 --browserUrl http://127.0.0.1:9222 \
  --no-usage-statistics --no-performance-crux \
  --no-category-performance --no-category-network --no-category-emulation \
  --screenshotFormat webp --screenshotMaxWidth 1280
```

Skill 要在任意仓库里可用，**不能只注册在单个项目**（`-s local` / `-s project` 都不行）。

## 为什么用 `--browserUrl` 而不是 `--autoConnect`

`--autoConnect` 走的是 Chrome 144+ 的权限式通道，每次新连接要在 Chrome 弹窗点一次 Allow。本机 Chrome 已经以 `--remote-debugging-port=9222` 运行且免授权，`--browserUrl` 直接连上去，**没有弹窗、没有人工授权环节**，更适合 Skill 自动化。

前置条件只有一个：Chrome 在 9222 上监听。自检：

```bash
curl -s http://127.0.0.1:9222/json/version | jq -r .Browser
```

没监听时（Chrome 重启过）用：

```bash
open -a "Google Chrome" --args --remote-debugging-port=9222
```

## 这个连接看得到什么

连的是你日常 Profile，MCP 能列出**全部标签页**——包括代码托管、企业后台、云控制台、内网系统，其中一部分的 URL 本身就带凭证（不少控制台会把 token 或 apiKey 放在 query string 里）。

因此 Skill 侧有一条硬约束（`AGENTS.md` §6-2）：任何 `click` / `fill` / `type_text` / `upload_file` 之前必须先校验目标页 host ∈ `chatgpt.com`，不匹配立即停止。**边界靠这条规则守，不靠"记得关掉敏感页面"。**

## 版本策略

锁 `@1.7.0`，不用 `@latest`。升级前先 `npx -y chrome-devtools-mcp@<新版本> --help` 比对 flag。
