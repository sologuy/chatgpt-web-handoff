#!/bin/bash
# 真实运行安装器和 CLI --help；只写临时目录，不使用真实用户 Skill 目录或浏览器。
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${CGH_PYTHON:-python3}" - "$REPO" <<'PY'
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

repo = Path(sys.argv[1])
bash = shutil.which("bash")
checks = 0


def check(condition, message):
    global checks
    if not condition:
        raise AssertionError(message)
    checks += 1
    print(f"PASS {checks:02d} {message}", flush=True)


def snapshot(root):
    result = {}
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                value = ("symlink", os.readlink(path), path.lstat().st_mtime_ns)
            elif path.is_dir():
                value = ("dir",)
            else:
                value = ("file", path.read_bytes())
            result[str(path.relative_to(root))] = value
    return result


with tempfile.TemporaryDirectory(prefix="cgh-install-") as temporary:
    base = Path(temporary)
    minimal = base / "minimal-bin"
    minimal.mkdir()
    for name in ("cat", "dirname", "mkdir", "ln", "readlink"):
        command = shutil.which(name)
        if not command:
            raise RuntimeError(f"缺少安装基本命令 {name}")
        (minimal / name).symlink_to(command)
    (minimal / "python3").symlink_to(sys.executable)
    # 该 PATH 没有 node/npx/claude/curl；成功安装不能依赖或探测它们。
    env = dict(os.environ, PATH=str(minimal), CGH_PYTHON=sys.executable,
               CGH_LEDGER=str(base / "ledger.jsonl"), PYTHONDONTWRITEBYTECODE="1")
    roots = (".claude", ".agents", ".codex")
    skills = {"handoff": "chatgpt-handoff", "image": "chatgpt-image-gen"}

    def install(root, *args, source=repo, expected=0, overrides=None, cwd=None):
        run_env = dict(env, CGH_INSTALL_HOME=str(root))
        run_env.update(overrides or {})
        result = subprocess.run([bash, str(source / "scripts/install.sh"), *args],
                                env=run_env, cwd=cwd or base, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if (result.returncode == 0) != (expected == 0):
            raise AssertionError(f"install {args}: code={result.returncode}\n{result.stdout}\n{result.stderr}")
        return result

    def linked(root, selected, source=repo, hermes=False):
        harnesses = roots + ((".hermes",) if hermes else ())
        for harness in harnesses:
            for short, skill in skills.items():
                entry = root / harness / "skills" / skill
                if short in selected:
                    if not entry.is_symlink() or entry.resolve() != (source / "skills" / skill).resolve():
                        return False
                elif os.path.lexists(entry):
                    return False
        return True

    default = base / "default"
    install(default)
    check(linked(default, {"handoff"}) and not (default / ".hermes").exists(),
          "默认仅安装 handoff，未创建 Hermes")
    explicit = base / "explicit"
    install(explicit, "--skills", "handoff")
    check(linked(explicit, {"handoff"}), "显式 handoff 与默认一致")
    image = base / "image"
    install(image, "--skills", "image")
    check(linked(image, {"image"}), "image-only 不创建 handoff 发现入口")
    result = subprocess.run([str(image / ".agents/skills/chatgpt-image-gen/cgimg"), "--help"],
                            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check(result.returncode == 0 and "--ref" in result.stdout,
          "image-only 经 Skill 相对链接加载同仓依赖并运行 CLI")

    both = base / "all"
    (both / ".hermes").mkdir(parents=True)
    install(both, "--skills", "all")
    check(linked(both, {"handoff", "image"}, hermes=True), "all 安装已有 Hermes 在内的四端入口")
    before = snapshot(both)
    install(both, "--skills", "all")
    check(snapshot(both) == before, "重复安装幂等，现有链接未重建")
    old_image = snapshot(image)
    install(image, "--skills", "handoff")
    check(linked(image, {"handoff", "image"}) and all(snapshot(image).get(k) == v for k, v in old_image.items()),
          "增量安装保留未选 image 入口")
    unselected = base / "unselected"
    untouched = unselected / ".claude/skills/chatgpt-handoff"
    untouched.mkdir(parents=True)
    (untouched / "local.txt").write_text("user-owned", encoding="utf-8")
    before = snapshot(untouched)
    install(unselected, "--skills", "image")
    check(snapshot(untouched) == before, "未选 Skill 的实体目录保留原样")

    for kind in ("file", "directory", "parent"):
        conflict = base / f"conflict-{kind}"
        early = conflict / ".claude/skills/chatgpt-handoff"
        early.parent.mkdir(parents=True)
        early.symlink_to(base / "old-checkout/skills/chatgpt-handoff")
        late = conflict / ".codex/skills"
        late.parent.mkdir(parents=True)
        if kind == "parent":
            late.write_text("keep parent", encoding="utf-8")
        else:
            late.mkdir()
            target = late / "chatgpt-image-gen"
            if kind == "file":
                target.write_text("keep file", encoding="utf-8")
            else:
                target.mkdir()
                (target / "local.txt").write_text("keep dir", encoding="utf-8")
        before = snapshot(conflict)
        install(conflict, "--skills", "all", expected=1)
        check(snapshot(conflict) == before, f"后段 {kind} 冲突失败且全部目标零修改")

    for index, args in enumerate((("--skills", "bad"), ("--skills",), ("--unknown",))):
        invalid = base / f"invalid-{index}"
        install(invalid, *args, expected=1)
        check(not invalid.exists(), f"非法参数 {args} 拒绝且不创建安装根")
    bad_python = base / "bad-python"
    install(bad_python, "--skills", "all", overrides={"CGH_PYTHON": str(base / "no-python")}, expected=1)
    check(not bad_python.exists(), "缺少 Python 时不写入口")
    for index, args in enumerate((("--register-mcp", "--skills", "all"), ("--skills", "all", "--register-mcp"))):
        mcp = base / f"mcp-{index}"
        result = install(mcp, *args, expected=1)
        check(not mcp.exists() and "需要 node" in result.stderr,
              f"MCP 参数顺序 {index + 1} 正确，缺依赖在写入口前拒绝")
    check(not (base / "ledger.jsonl").exists(), "纯安装与 --help 不写账本")

    help_root = base / "help-only"
    result = install(help_root, "--help")
    check(not help_root.exists() and "--skills" in result.stdout, "安装帮助可独立读取且不创建目录")

    legacy = base / "legacy-repo"
    legacy.mkdir()
    old_artifact = legacy / ".ai/handoffs"
    old_artifact.mkdir(parents=True)
    (old_artifact / "keep.txt").write_text("untouched", encoding="utf-8")
    (legacy / ".gitignore").write_text(".ai/handoffs/\n", encoding="utf-8")
    before = snapshot(legacy)
    install(base / "legacy-install", "--skills", "all", cwd=legacy)
    check(snapshot(legacy) == before, "安装自检不迁移调用目录里的旧作业产物")

    spaced_repo = base / "checkout with spaces"
    spaced_repo.mkdir()
    for directory in ("bin", "skills", "templates", "scripts"):
        shutil.copytree(repo / directory, spaced_repo / directory, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    spaced_home = base / "install root with spaces"
    install(spaced_home, "--skills", "all", source=spaced_repo)
    statuses = []
    for skill, cli in (("chatgpt-handoff", "cgh"), ("chatgpt-image-gen", "cgimg")):
        result = subprocess.run([str(spaced_home / ".codex/skills" / skill / cli), "--help"],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        statuses.append(result.returncode)
    check(linked(spaced_home, {"handoff", "image"}, source=spaced_repo) and statuses == [0, 0],
          "仓库与安装根含空格时两个 Skill CLI 均可运行")

print(f"安装集成验证通过：{checks} 项；未连接浏览器，未修改 HOME。")
PY
