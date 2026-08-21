# AGENTS.md

给在这个仓库里干活的 AI 编码助手（Claude Code / Codex / DSH 等）看的规则。
`CLAUDE.md` 通过 `@AGENTS.md` 导入本文件。全程简体中文。

---

## 1. 这是什么

**chatgpt-web-handoff（cgh）**：把编码 agent 当前任务的上下文，交接给
**你日常那个 Chrome 里已登录的 ChatGPT Web** 做独立审查，再把结构化结论取回本地仓库。

形态：一个薄的确定性 CLI（`bin/cgh` + `bin/cgh_cdp.py` + `bin/cgh_web.py`）+ 一个 Skill。
**不常驻服务、不写浏览器插件、不做 Native Messaging、不自建 Broker、不另起 Chrome Profile。**

明确非目标：不做 ChatGPT API 替代品；不做通用浏览器自动化框架；
不做多账号 / 多并发调度；不保存或搬运登录凭证。

## 2. 改代码前先读

| 顺序 | 文件 | 作用 |
|------|------|------|
| ① | 本文件 §6 | 硬约束，不可违反 |
| ② | `bin/cgh` 的模块 docstring | 作业目录、`job.json` 字段、状态机、哨兵格式 |
| ③ | `bin/cgh_web.py` 的注释 | ChatGPT 真实 UI 的锚点、档位标签、附件行为、后台标签页解冻 |
| ④ | `CONTRIBUTING.zh-CN.md` | 分层边界、怎么验证改动 |

## 3. 怎么验证改动

**本项目不写单元测试**，验证靠真跑——干跑测不出浏览器那一半。

改完 `bin/` 里任何东西：

1. `./bin/cgh doctor` 通过
2. 在一个临时 git 仓库里跑一遍 `new` / 单活跃拦截 / 状态机 / `parse` 哨兵解析
3. **再用 `cgh submit` 实跑一次低档位作业**——这一步不能省

## 4. Git

| 分支 | 用途 |
|------|------|
| `main` | 稳定基线，只接受合并 + tag |
| `dev` | 日常工作分支 |
| `task/<name>` | 跨多日或有风险的任务 |

commit 格式：`<type>: <中文摘要>`，type ∈ `docs` / `feat` / `fix` / `chore` / `design`。
提交前 `git status --short` 审查，确认没有凭证、没有 `.env`、
没有 `.chatgpt/web-handoff/` 作业产物。

## 5. 目录

| 目录 | 职责 |
|------|------|
| `bin/` | CLI 与浏览器编排（`cgh` 账本 / `cgh_cdp` 传输 / `cgh_web` ChatGPT 语义） |
| `skills/chatgpt-handoff/` | Skill 真相源，`scripts/install.sh` 会 symlink 出去 |
| `templates/handoff/` | `request.md` / `followup.md` / `job.json` 模板（运行时依赖） |
| `scripts/` | 安装脚本 |

Handoff 作业产物落在**使用方仓库**的 `.chatgpt/web-handoff/<job_id>/`，不落在本仓库。
本仓库的 `.chatgpt/web-handoff/` 只用于自测，整目录已 gitignore。

---

## 6. 硬约束（实现时不可违反）

1. **不落凭证**：任何环节不读取、不复制、不持久化 cookie / session token / 账号密码。日志、快照、`job.json`、`request.md` 里都不得出现凭证或 `Authorization` 头。
2. **页面白名单**：任何 `click` / `fill` / `type_text` / `upload_file` 之前，必须先确认当前 page 的 host ∈ `chatgpt.com` / `chat.openai.com`。不匹配立即停止并置状态 `wrong_page`，不试探、不猜测。
3. **effort 不静默降级**：请求的推理档位在 UI 里找不到时，置 `effort_not_found` 并列出实际可选项，交由用户或配置决定，**禁止悄悄用低档跑完再交付**。`job.json` 必须同时记录 `effort_requested` 与 `effort_actual`。
4. **不静默点坐标**：元素定位优先级 —— ① a11y role + accessible name ② 页面可见文本 ③ `data-testid` / `data-message-author-role` ④ 失败则保存 `failed-snapshot.txt` + `failed-page.webp` 并置 `ui_changed`。禁止写死 CSS selector，禁止凭坐标盲点。
5. **不阻塞**：`submit` 发送成功后立即返回 `job_id`；`poll` 单次调用只读一次状态就返回，**不在一次工具调用里自旋等待**。
6. **单活跃作业**：`max_active_jobs = 1`，用 lockfile 实际拦截（不只是写在文档里）。并发需求等 V2 的 `--experimentalPageIdRouting`。
7. **浏览器通道**（v0.4 改）：稳定提交路径必须由确定性代码执行，
   主驱动是 `bin/cgh_cdp.py` 的自有 raw CDP；`chrome-devtools-mcp` 降为**探测 / 诊断 / UI 改版适配**用途，
   不参与正常 handoff。**禁止用 Playwright 连本机 9222 的 Chrome**——旧版 `connectOverCDP()` 会替换
   Chrome 的下载委托，下载文件变成无扩展名的 `playwright-artifacts-*`，断开或杀进程都不恢复，只能重启 Chrome。
   也不要在跑 handoff 时同时挂 claude-in-chrome，两个自动化通道会互抢标签页和焦点。
   CDP 层只保留传输与通用页面操作，**业务语义一律留在 `cgh_web.py`**，不要把它养成通用 DevTools 框架。
8. **使用边界**：不做团队共享服务、不做批量任务、不对外提供 API。
9. **不改写原文**：`result.md` 保存 ChatGPT 原始输出 + 解析出的结构化块。不做"总结的总结"，不删少数派意见，不把不确定结论写成确定结论。
10. **产物默认不进使用方 git**：`cgh` 在使用方仓库创建 `.chatgpt/web-handoff/` 时，必须同时确保其被 gitignore（`request.md` 含用户代码上下文，`result.md` 含外部模型输出）。

---

---

## 7. 常用命令

```bash
# 9222 探活：连不上就没法干活，这是第一步
curl -s http://127.0.0.1:9222/json/version | jq -r .Browser
# 没监听时（Chrome 重启过）：
#   open -a "Google Chrome" --args --remote-debugging-port=9222
# 不要自作主张重启用户的 Chrome，先问

# 找 ChatGPT 标签页
curl -s http://127.0.0.1:9222/json/list \
  | jq -r '.[]|select(.type=="page")|"\(.id[0:8])  \(.url)"' | grep chatgpt

# 安装与自检
./scripts/install.sh
./bin/cgh doctor
```

---

## 8. 本地私有约定

如果仓库根目录存在 `AGENTS.local.md`（不进 git），一并遵守——
那里放的是维护者本人的工作流约定（任务总线、文档编号、阶段状态），
对外部使用者没有意义，所以不公开。
