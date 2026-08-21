#!/bin/bash
# 安装 chatgpt-handoff：环境自检 + Skill symlink（+ 可选注册 MCP）
# 用法：./scripts/install.sh [--register-mcp]
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 解释器：CGH_PYTHON 优先，否则用 PATH 里的 python3。
# bin/cgh 的 shebang 是 #!/usr/bin/env python3，这里只做版本自检，不写死路径。
PY="${CGH_PYTHON:-$(command -v python3 || true)}"
MCP_VERSION=1.7.0
BROWSER_URL=http://127.0.0.1:9222
SKILL_LINK="$HOME/.claude/skills/chatgpt-handoff"
# ~/.agents/skills 是 Codex / DSH 共读的用户级 skill 目录（DSH 的 agentsHome 默认就是它）。
AGENTS_SKILL_LINK="$HOME/.agents/skills/chatgpt-handoff"
CODEX_SKILL_LINK="$HOME/.codex/skills/chatgpt-handoff"

ok(){ printf '  ✅ %s\n' "$1"; }
no(){ printf '  ❌ %s\n' "$1"; FAIL=1; }
warn(){ printf '  ⚠️  %s\n' "$1"; }
FAIL=0

echo "== 环境自检 =="

if [ -n "$PY" ] && [ -x "$PY" ]; then
  PYV="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0)"
  if [ "$(printf '%s\n3.9\n' "$PYV" | sort -V | head -1)" = "3.9" ]; then
    ok "Python: $("$PY" --version 2>&1)  ($PY)"
  else
    no "Python 版本过低：$PYV（需要 >= 3.9）。用 CGH_PYTHON=/path/to/python3 指定"
  fi
else
  no "找不到 python3。用 CGH_PYTHON=/path/to/python3 ./scripts/install.sh 指定"
fi

if command -v node >/dev/null 2>&1; then ok "Node: $(node -v)"
else no "找不到 node（npx 需要它来跑 MCP）"; fi

if BROWSER=$(curl -s --max-time 5 "$BROWSER_URL/json/version" 2>/dev/null | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["Browser"])' 2>/dev/null); then
  ok "Chrome CDP 可达：$BROWSER"
  if curl -s --max-time 5 "$BROWSER_URL/json/list" 2>/dev/null | grep -q 'chatgpt\.com'; then
    ok "已有 chatgpt.com 标签页"
  else
    warn "没找到 chatgpt.com 标签页（首次使用时 Skill 会自己开，但要确保已登录）"
  fi
else
  no "连不上 $BROWSER_URL —— 先跑：open -a \"Google Chrome\" --args --remote-debugging-port=9222"
fi

echo
echo "== 安装 Skill（Claude Code / Codex / DSH 共用同一份） =="
for link in "$SKILL_LINK" "$AGENTS_SKILL_LINK" "$CODEX_SKILL_LINK"; do
  mkdir -p "$(dirname "$link")"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    no "$link 已存在且不是 symlink，请先手工处理（不覆盖你的文件）"
  else
    ln -sfn "$REPO/skills/chatgpt-handoff" "$link"
    ok "$link → $REPO/skills/chatgpt-handoff"
  fi
done

echo
echo "== cgh 自检 =="
if "$REPO/bin/cgh" list >/dev/null 2>&1; then ok "cgh 可执行"
else no "cgh 跑不起来，检查 shebang 与执行位"; fi

echo
echo "== MCP =="
MCP_CMD=(claude mcp add chrome-devtools -s user --
  npx -y "chrome-devtools-mcp@$MCP_VERSION" --browserUrl "$BROWSER_URL"
  --no-usage-statistics --no-performance-crux
  --no-category-performance --no-category-network --no-category-emulation
  --screenshotFormat webp --screenshotMaxWidth 1280)

if [ "${1:-}" = "--register-mcp" ]; then
  "${MCP_CMD[@]}" && ok "已注册（user scope）；需重启 Claude Code 才会加载工具"
else
  echo "  未注册。要注册请跑 ./scripts/install.sh --register-mcp，或手工执行："
  printf '    %s\n' "${MCP_CMD[*]}"
  echo "  注意：user scope 会让 chrome-devtools 工具在你所有项目里加载。"
fi

echo
if [ "$FAIL" = 1 ]; then echo "结果：有未通过项，先修上面的 ❌"; exit 1; fi
echo "结果：OK。用法 /chatgpt-handoff <要审什么>（不指定档位就走默认「极高」；可选 极速/中级/高级/极高/pro）"
echo "Ready. Usage: /chatgpt-handoff <what to review>   (default tier: xhigh; also instant/medium/high/xhigh/pro)"
echo "Next: ./bin/cgh doctor"
