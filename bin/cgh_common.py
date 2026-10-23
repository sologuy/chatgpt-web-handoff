"""cgh / cgimg 共用的来源、账本和浏览器提交锁。"""

import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class BrowserBusy(Exception):
    """提交锁超时；由调用方决定 CLI 错误输出。"""

    def __init__(self, path, timeout):
        self.path = path
        self.timeout = timeout
        super().__init__(f"浏览器提交锁忙碌：{path}（等待 {timeout}s）")


class BrowserLock:
    """全机互斥，只保护「设档位 → 发送确认」过程。

    ChatGPT 的推理强度是**账号级持久化偏好**，跨标签页实时同步（2026-08-19 实测：
    A 页改成极速，B 页不刷新就跟着变，且中途会短暂显示一个谁都没设过的中间值）。
    所以两个 harness 同时提交、要的档位不同时，会互相把对方的档位改掉，
    而各自回读都"正确"，事后查不出来。

    这里刻意**不锁整个作业**：生成阶段（Pro 可达十分钟）不碰这个共享偏好，
    锁它只会白白扼杀并发。锁住的只有 configure→发送确认 这个真正的临界区。
    """

    def __init__(self, timeout=180):
        self.path = Path.home() / ".cgh" / "browser.lock"
        self.timeout = timeout
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.time() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.ftruncate(self.fd, 0)
                os.write(self.fd, f"{os.getpid()} {now()}\n".encode())
                return self
            except BlockingIOError:
                if time.time() >= deadline:
                    os.close(self.fd)
                    self.fd = None
                    raise BrowserBusy(self.path, self.timeout)
                time.sleep(0.2)

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


# 干跑测试要把账本指到别处，否则测试作业会污染真实的跨仓统计
LEDGER = Path(os.environ.get("CGH_LEDGER") or (Path.home() / ".cgh" / "ledger.jsonl"))


def _git_state(root):
    def q(*args):
        try:
            r = subprocess.run(["git", "-C", str(root), *args],
                               capture_output=True, text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None
    head = q("rev-parse", "--short", "HEAD")
    return {"git_head": head,
            "git_branch": q("rev-parse", "--abbrev-ref", "HEAD"),
            "git_dirty": bool(q("status", "--porcelain")) if head else None}


def detect_origin(root):
    """记下「谁在什么状态下发起的这次交接」。

    只按白名单取字段——**绝不遍历 env**，那里面有 CLAUDE_CODE_MESSAGING_TOKEN 这类东西。
    transcript 只记真实存在的路径：宁可记 null，也不留一条查不到的线索。
    """
    e = os.environ
    o = {"harness": "unknown", "ai_agent": e.get("AI_AGENT"),
         "version": None, "session_id": None, "transcript": None}

    if e.get("CLAUDECODE") or e.get("CLAUDE_CODE_SESSION_ID"):
        o["harness"] = "claude-code"
        o["version"] = e.get("CLAUDE_CODE_VERSION")
        o["session_id"] = e.get("CLAUDE_CODE_SESSION_ID")
        if o["session_id"]:
            # 目录名是启动时 cwd 的 slug，不一定等于仓库根，所以搜一遍
            hits = list((Path.home() / ".claude" / "projects").glob(f"*/{o['session_id']}.jsonl"))
            o["transcript"] = str(hits[0]) if hits else None
    elif e.get("DSH_SESSION_ID"):
        # DSH 把会话 id 注入**工具 shell**（不是服务进程，去翻服务进程的 env 会扑空）。
        # 不要取 DSH_PTY_SESSION_ID——那是底层终端进程 id，不是对话 id。
        o["harness"] = "dsh"
        o["session_id"] = e.get("DSH_SESSION_ID")
        # DSH_HOME 是按项目走的，不能假定 ~/.dsh
        home = e.get("DSH_HOME")
        if home:
            hits = list(Path(home).glob(f"sessions/*/{o['session_id']}/session.jsonl.zstd"))
            o["transcript"] = str(hits[0]) if hits else None
    elif e.get("CODEX_SESSION_ID"):
        # Codex CLI 原生。会话记录：~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<sid>.jsonl
        o["harness"] = "codex"
        o["session_id"] = e.get("CODEX_SESSION_ID")
        hits = list((Path.home() / ".codex" / "sessions").glob(
            f"*/*/*/rollout-*-{o['session_id']}.jsonl"))
        o["transcript"] = str(hits[0]) if hits else None
    elif e.get("CODEX_COMPANION_SESSION_ID"):
        o["harness"] = "codex-companion"
        o["session_id"] = e.get("CODEX_COMPANION_SESSION_ID")
        t = e.get("CODEX_COMPANION_TRANSCRIPT_PATH")
        o["transcript"] = t if t and Path(t).exists() else None
    elif e.get("HERMES_SESSION_ID"):
        # 放在最后一个分支：Hermes 会派生 codex 子任务，那种情况下两个 id 都在，
        # 但真正在跑 cgh 的是 codex，不是 Hermes。
        o["harness"] = "hermes"
        o["session_id"] = e.get("HERMES_SESSION_ID")
        # 会话文件名是 <时间戳>_<id>.jsonl，而 id 到底是整段还是尾段没有定论，
        # 所以两头都用通配；匹配不上就照旧记 null，不猜。
        home = Path(e.get("HERMES_HOME") or (Path.home() / ".hermes"))
        hits = list(home.glob(f"sessions/*{o['session_id']}*.jsonl"))
        o["transcript"] = str(hits[0]) if len(hits) == 1 else None
    else:
        # 认不出的 harness：AI_AGENT 原值照记，另外记下有哪些
        # *_SESSION_ID 变量**的名字**（只记名字不记值）——下次看账本就知道该接哪个。
        names = sorted(k for k in e if k.endswith("_SESSION_ID"))
        if names:
            o["session_env_names"] = names

    o.update(_git_state(root))
    o["cwd"] = str(root)
    return o


def _ledger_record(ev, root, job, **extra):
    origin = job.get("origin") or {}
    rec = {"ts": extra.pop("ts_override", None) or now(), "ev": ev, "repo": str(root), "id": job.get("id"),
           "harness": origin.get("harness"), "session_id": origin.get("session_id"),
           "action": job.get("action"), "subject": job.get("subject"),
           "effort_requested": job.get("effort_requested"),
           "effort_actual": job.get("effort_actual"),
           "parent_id": job.get("parent_id"),
           "conversation_url": job.get("conversation_url")}
    rec.update(extra)
    return rec


def _write_ledger(f, rec):
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    f.flush()                       # 必须在仍持锁时写出缓冲，不能先解锁再等 close


def ledger_append(ev, root, job, **extra):
    """全机账本。作业散在各使用方仓库里，没有这个就没有跨仓视图。

    append-only + flock —— 多仓库并发是本项目明确支持的场景，不能互相踩。
    账本写失败告警并返回 False，但不能让已发送的 handoff 被误判成需要重投。
    """
    try:
        rec = _ledger_record(ev, root, job, **extra)
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            _write_ledger(f, rec)
        return True
    except Exception as exc:
        print(f"cgh: ledger_write_failed: {LEDGER} ({type(exc).__name__}); "
              f"id={job.get('id')} ev={ev}，handoff 状态不受影响，请核对后补漏", file=sys.stderr)
        return False
