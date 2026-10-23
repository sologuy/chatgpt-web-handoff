#!/bin/bash
# 各 harness 的发现入口都指向本仓库；纯安装不访问浏览器。
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/install.sh [--skills handoff|image|all] [--register-mcp]

  --skills         默认 handoff；image 可独立安装，all 安装两个 Skill
  --register-mcp   可选注册 Claude Code 的 Chrome DevTools 诊断 MCP
  CGH_INSTALL_HOME 可选安装根（默认当前 HOME）；用于隔离安装，不修改 HOME
  CGH_PYTHON       可选 Python 解释器，用于安装预检（需要 >= 3.9）
EOF
}

SELECTION=handoff
REGISTER_MCP=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --skills)
      [ "$#" -ge 2 ] || { echo "--skills 缺少 handoff|image|all" >&2; exit 2; }
      SELECTION="$2"; shift 2 ;;
    --register-mcp) REGISTER_MCP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
  esac
done
case "$SELECTION" in
  handoff) SKILLS=(chatgpt-handoff); CLIS=(cgh) ;;
  image) SKILLS=(chatgpt-image-gen); CLIS=(cgimg) ;;
  all) SKILLS=(chatgpt-handoff chatgpt-image-gen); CLIS=(cgh cgimg) ;;
  *) echo "无效 --skills：$SELECTION（应为 handoff|image|all）" >&2; exit 2 ;;
esac

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_HOME="${CGH_INSTALL_HOME:-$HOME}"
PY="${CGH_PYTHON:-python3}"
PY="$(command -v "$PY" || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "需要 Python >= 3.9；可用 CGH_PYTHON=/path/to/python3 指定安装预检解释器" >&2
  exit 1
fi
INSTALL_HOME="$("$PY" -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$INSTALL_HOME")"

echo "== 安装预检（$SELECTION） =="
ROOTS=("$INSTALL_HOME/.claude/skills" "$INSTALL_HOME/.agents/skills" "$INSTALL_HOME/.codex/skills")
# 没安装 Hermes 时不凭空创建它的目录。
[ ! -d "$INSTALL_HOME/.hermes" ] || ROOTS+=("$INSTALL_HOME/.hermes/skills")
LINKS=()
SOURCES=()
for index in "${!SKILLS[@]}"; do
  skill="${SKILLS[$index]}"
  cli="${CLIS[$index]}"
  [ -f "$REPO/skills/$skill/SKILL.md" ] && [ -x "$REPO/skills/$skill/$cli" ] || {
    echo "缺少 Skill 或可执行入口：$skill/$cli" >&2; exit 1;
  }
  # --help 只检查加载与参数入口；不能调用 list，它可能迁移当前仓库的旧作业。
  PYTHONDONTWRITEBYTECODE=1 "$PY" "$REPO/skills/$skill/$cli" --help >/dev/null
  for root in "${ROOTS[@]}"; do
    LINKS+=("$root/$skill")
    SOURCES+=("$REPO/skills/$skill")
  done
done

# 检查所有目标及其父目录后才开始写入，避免后面的实体冲突造成半套安装。
"$PY" - "${LINKS[@]}" <<'PY'
import os
import sys

errors = []
for link in sys.argv[1:]:
    if os.path.lexists(link) and not os.path.islink(link):
        errors.append(f"{link} 已存在且不是 symlink（保留原件，不覆盖）")
    parent = os.path.dirname(link)
    while parent and parent != os.path.dirname(parent):
        if os.path.lexists(parent):
            if not os.path.isdir(parent):
                errors.append(f"{parent} 不是可用目录")
            elif not os.access(parent, os.W_OK | os.X_OK):
                errors.append(f"{parent} 不可写")
            break
        parent = os.path.dirname(parent)
if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
PY

MCP_VERSION=1.7.0
BROWSER_URL=http://127.0.0.1:9222
if [ "$REGISTER_MCP" = 1 ]; then
  for dependency in node npx claude; do
    command -v "$dependency" >/dev/null 2>&1 || {
      echo "--register-mcp 需要 $dependency；未写入任何 Skill 入口" >&2; exit 1;
    }
  done
fi

echo "== 安装 Skill（各 harness 共用同一份） =="
for index in "${!LINKS[@]}"; do
  link="${LINKS[$index]}"
  source="${SOURCES[$index]}"
  mkdir -p "$(dirname "$link")"
  if [ ! -L "$link" ] || [ "$(readlink "$link")" != "$source" ]; then
    ln -sfn "$source" "$link"
  fi
  printf '  ✅ %s → %s\n' "$link" "$source"
done

if [ "$REGISTER_MCP" = 1 ]; then
  claude mcp add chrome-devtools -s user -- \
    npx -y "chrome-devtools-mcp@$MCP_VERSION" --browserUrl "$BROWSER_URL" \
    --no-usage-statistics --no-performance-crux \
    --no-category-performance --no-category-network --no-category-emulation \
    --screenshotFormat webp --screenshotMaxWidth 1280
  echo "已注册诊断 MCP（user scope）；重启 Claude Code 后加载。正常执行不依赖 MCP。"
fi

echo "结果：安装完成。运行时需要 PATH 中的 Python >= 3.9，以及已登录 ChatGPT 的 Chrome CDP 会话。"
echo "安装未连接或启动 Chrome。运行前自检：$REPO/bin/cgh doctor"
echo "Skill 入口：${SKILLS[*]}"
