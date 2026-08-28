"""ChatGPT Web 编排 —— 把 v1 里散在 Skill 提示词里的二十来步浏览器操作固化成确定性流程。

每一步的做法都来自真实 handoff 的实测，逐处写在下面的注释里：
- 档位子菜单要先展开「显示高级选项」才暴露「推理强度」行
- 正文注入必须走 paste 事件；敲键盘会在换行处提前发送
- 发送后 URL 要等到服务端真 id，中间会短暂停在 /c/WEB:<临时id>
"""

import json
import os
import time
from pathlib import Path

import cgh_cdp as cdp
from cgh_cdp import CdpError

CHATGPT_HOSTS = {"chatgpt.com", "chat.openai.com"}

# 本项目只调推理强度、不切模型。模型钉死在这里，实测漂了就停下报人，
# 不要闷头用另一个模型跑完再交付——那是「能跑通但语义错误」那一类缺陷。
# 模型升级时改这一行（Skill 是热加载的，不用重启会话）。
EXPECTED_MODEL = os.environ.get("CGH_EXPECTED_MODEL", "GPT-5.6 Sol")

# 页面加载/控件就绪的等待上限。30s 实测太紧：两个标签页同时加载时，composer 要 33s
# 才挂载，会把「还没加载完」误报成 ui_changed（ChatGPT 改版）。这两件事的处置完全不同，
# 误报的代价是让人去查一个根本不存在的改版。
PAGE_TIMEOUT = 60

# 每档的标签候选。中文项是 2026-08-19 实测（界面语言 zh-CN）；
# 英文项未实测，只作候选——命中不了照样置 effort_not_found 停下问人，不静默降级。
# 首项是"想要的那个"，用于日志与回读比对。
EFFORT_LABELS = {
    "instant": ["极速", "Instant"],
    "medium": ["中", "Medium"],
    "high": ["高", "High"],
    "xhigh": ["极高", "Extra High", "XHigh"],
    "pro": ["Pro"],
}


def _labels(effort):
    return EFFORT_LABELS.get(effort, [effort])


class WrongPage(CdpError):
    pass


class EffortNotFound(CdpError):
    def __init__(self, wanted, available):
        super().__init__(f"档位 {wanted} 不在可选项里：{available}")
        self.wanted = wanted
        self.available = available


# ---------------------------------------------------------------- JS 片段

_EFFORT_BTN = """(() => {
  const form = document.querySelector('form');
  if (!form) return null;
  const btns = [...form.querySelectorAll('button[aria-haspopup="menu"]')]
    .filter(b => b.getAttribute('data-testid') !== 'composer-plus-btn');
  return btns.length ? btns[btns.length - 1] : null;
})()"""

_PICKER = '[data-testid="composer-intelligence-picker-content"]'


def _wait(page, expr, what, timeout=20, interval=0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if page.evaluate(expr):
            return True
        time.sleep(interval)
    raise CdpError(f"等待超时（{timeout}s）：{what}")


# ---------------------------------------------------------------- 白名单

def guard_host(page):
    """硬约束 §6.2：任何交互前先确认 host，不匹配立即抛错，不试探。"""
    host = page.host()
    if host not in CHATGPT_HOSTS:
        raise WrongPage(f"目标页 host={host}，不在白名单 {sorted(CHATGPT_HOSTS)}")
    return host


def check_login(page):
    return page.evaluate(
        "!/\\/auth|\\/login/.test(location.pathname) && !!document.querySelector('#prompt-textarea')"
    )


# ---------------------------------------------------------------- 开新会话

def _find_blank_chat(owned_ids=()):
    """找一个可复用的空白新会话页。

    五条同时成立才复用：**是我们自己开过的**（targetId 在 owned_ids 里）、URL 是根路径、
    没有任何消息、输入框是空的、**没有遗留附件**。

    最后一条是 2026-08-21 补的：附件不随 selectAll+delete 消失，上一个作业失败后
    可能在页面上留下 chip。复用这种页面会把别人的上下文一起发出去，还返回成功。
    这里不做清理、直接跳过——脏页面另开一个更省事，清理留给 inject() 自己那次。

    「是我们自己开过的」这条不能省：光看页面形态，会把用户刚手动开、正准备自己用的
    空白 ChatGPT 页抢过来打字。这是用户日常在用的 Chrome。
    """
    owned = set(owned_ids)
    if not owned:
        return None, None
    for p in cdp.list_pages():
        if p.get("id") not in owned:
            continue
        if p.get("url", "").rstrip("/") not in ("https://chatgpt.com", "https://chat.openai.com"):
            continue
        try:
            page = cdp.attach(p["id"])
            clean = page.evaluate(
                "(() => document.querySelectorAll('[data-message-author-role]').length === 0"
                " && !!document.querySelector('#prompt-textarea')"
                " && document.querySelector('#prompt-textarea').innerText.trim() === '')()"
            )
            if clean and (count_chips(page) or count_uploads(page)):
                clean = False          # 有遗留附件或上传件，这页不能用
            if clean:
                return page, p["id"]
            page.close()
        except (CdpError, OSError):
            # 冻结的页 evaluate 永不返回，socket 抛的是裸 TimeoutError（OSError 子类）。
            # 这只说明这一页不能复用，不该让整个 submit 陪葬。
            continue
    return None, None


def open_new_chat(timeout=PAGE_TIMEOUT, owned_ids=()):
    """开一个干净的新会话页，绝不复用用户已有的对话页。

    owned_ids 是本仓库历史作业用过的 targetId，只在这个集合里找可复用的空白页。
    """
    page, target_id = _find_blank_chat(owned_ids)
    if page is None:
        page, target_id = cdp.open_page("https://chatgpt.com/", timeout=timeout)
    try:
        # 后台新标签页会被 Chrome 立刻降频（页面一多尤其明显），第一次 evaluate
        # 可能直接超时而不是返回慢。所以先把它唤醒——unfreeze 自带 30s 预算和重试，
        # 主线程忙不会误判，反过来省掉后面每一次 evaluate 都要自己扛超时。
        page.unfreeze()
        guard_host(page)
        _wait(page, "!!document.querySelector('#prompt-textarea')", "输入框就绪", timeout)
        _wait(page, f"(() => {{ const b = {_EFFORT_BTN}; return !!b && b.getBoundingClientRect().width > 0; }})()",
              "档位按钮就绪", timeout)
        if not check_login(page):
            raise CdpError("ChatGPT 未登录或被跳到登录页")
    except Exception:
        page.close()          # 只断 WS，标签页留着给人看现场
        raise
    return page, target_id


# ---------------------------------------------------------------- 档位

def read_effort(page):
    """当前推理强度。

    新版 UI 只在菜单展开时才显示它（旧版能直接从 composer 按钮上读），
    所以这里自己负责展开再还原。调用方不必关心——发送前复验和 doctor
    都是这么用的，让它们各自去开菜单只会把这件事重复三遍还容易漏。
    """
    opened = False
    if not _picker_open(page):
        _open_picker(page)
        opened = True
    try:
        st = page.evaluate(_EFFORT_STATE)
        return (st or {}).get("label")
    finally:
        if opened:
            _escape(page)


def list_effort_options(page):
    """枚举全部档位。会推动滑块，所以只在出错要报「实际有哪些档」时调。"""
    _, seen = _walk_efforts(page, [])
    return [{"label": x, "checked": None} for x in seen]


# 2026-08-28 改版：推理强度从「展开高级选项 → 点菜单项」变成了**一个 5 档滑块**，
# 只能用左右方向键推，点不动。同时「模型」不再折叠在高级选项里，直接是一组
# menuitemradio——注意 list_effort_options 以前正是靠 menuitemradio 取档位的，
# 现在那里装的是模型，照旧用会把模型名当成档位选项返回。
_SLIDER_CTRL = f"""(() => {{
  const g = document.querySelector('{_PICKER}');
  if (!g) return null;
  return [...g.querySelectorAll('[role=menuitem]')]
    .find(e => /^(能力|Capability)$/i.test(e.getAttribute('aria-label') || '')) || null;
}})()"""

# 当前档位读 aria-describedby 指向的实时描述：「极高，第 4 项，共 5 项。」
# 比 aria-valuenow 可靠——序号到名字的映射是 ChatGPT 定的，我们不该自己硬编。
_EFFORT_STATE = f"""(() => {{
  const g = document.querySelector('{_PICKER}');
  if (!g) return null;
  const s = g.querySelector('[role=slider]');
  const c = [...g.querySelectorAll('[role=menuitem]')]
    .find(e => /^(能力|Capability)$/i.test(e.getAttribute('aria-label') || ''));
  const ids = c ? (c.getAttribute('aria-describedby') || '').split(/\\s+/) : [];
  const txt = ids.map(i => (document.getElementById(i) || {{}}).innerText || '').join(' ');
  const m = txt.match(/^\\s*([^，,]+)[，,]\\s*第\\s*(\\d+)\\s*项/)
         || txt.match(/^\\s*([^,]+),\\s*item\\s*(\\d+)\\s*of\\s*(\\d+)/i);
  return {{now: s ? +s.getAttribute('aria-valuenow') : null,
           min: s ? +s.getAttribute('aria-valuemin') : null,
           max: s ? +s.getAttribute('aria-valuemax') : null,
           label: m ? m[1].trim() : null}};
}})()"""

_MODEL_CHECKED = f"""(() => {{
  const g = document.querySelector('{_PICKER}');
  if (!g) return null;
  const r = [...g.querySelectorAll('[role=menuitemradio]')]
    .find(x => x.getAttribute('aria-checked') === 'true')
    || g.querySelector('[role=menuitemradio]');
  return r ? r.innerText.replace(/\\s+/g, ' ').trim() : null;
}})()"""

_LEFT, _RIGHT = ("ArrowLeft", 37), ("ArrowRight", 39)


def _focus_slider(page):
    ok = page.evaluate("(() => { const c = " + _SLIDER_CTRL + "; if (c) c.focus(); return !!c; })()")
    if not ok:
        raise CdpError("定位失败：档位滑块（能力）")


def _effort_state(page):
    st = page.evaluate(_EFFORT_STATE)
    if not st or st.get("label") is None or st.get("now") is None:
        raise CdpError("定位失败：读不到档位滑块的当前值")
    return st


def _walk_efforts(page, wants):
    """从最低档一路推到最高，边推边记标签；碰到目标就停在那儿。

    返回 (命中的标签 or None, 走过的全部标签)。
    没有别的办法枚举——滑块只暴露当前这一档的名字，序号到名字的映射
    是 ChatGPT 定的，硬编在代码里改版就会错。
    """
    _focus_slider(page)
    st = _effort_state(page)
    page.press(*_LEFT, times=st["max"] - st["min"])          # 先归零
    seen = []
    for i in range(st["max"] - st["min"] + 1):
        cur = _effort_state(page)["label"]
        seen.append(cur)
        if cur in wants:
            return cur, seen
        if i < st["max"] - st["min"]:
            page.press(*_RIGHT)
    return None, seen


def _escape(page, times=2):
    for _ in range(times):
        page.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "windowsVirtualKeyCode": 27})
        page.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "windowsVirtualKeyCode": 27})
        time.sleep(0.2)


def _picker_open(page):
    return bool(page.evaluate(f"!!document.querySelector('{_PICKER}')"))


def _open_picker(page, attempts=3):
    """点开档位菜单。这个按钮是 toggle，所以每次都要先确认状态再决定点不点。"""
    for _ in range(attempts):
        if _picker_open(page):
            return
        page.click_js(_EFFORT_BTN, "composer 档位按钮")
        deadline = time.time() + 5
        while time.time() < deadline:
            if _picker_open(page):
                return
            time.sleep(0.25)
    raise CdpError("等待超时：档位菜单展开")


def configure(page, effort):
    """展开档位选择器，读回模型名，必要时改推理强度。

    返回 {model, effort_actual, available, touched}。

    这里刻意不做「已是目标档位就跳过」的优化：模型和当前档位都只在菜单里可见，
    不展开就读不到；而模型是钉死的（本项目只调推理强度、不切模型），
    每次提交都必须实测一眼，不能靠假设。
    """
    wants = _labels(effort)
    want = wants[0]
    # 复用的标签页上可能残留着上一轮打开的菜单。不先清场就点，等于把它关掉。
    _escape(page, 2)
    _open_picker(page)

    model = page.evaluate(_MODEL_CHECKED)
    st = _effort_state(page)

    if st["label"] in wants:
        _escape(page)
        return {"model": model, "effort_actual": st["label"], "available": [], "touched": False}

    before = st["now"]
    hit, seen = _walk_efforts(page, wants)
    if hit is None:
        # 没这一档就把滑块推回原位再报错——不能让一次失败的提交顺手改掉
        # 账号级的推理强度偏好，那会影响下一个作业。
        cur = _effort_state(page)["now"]
        if cur != before:
            key, vk = (_RIGHT if before > cur else _LEFT)
            page.press(key, vk, times=abs(before - cur))
        _escape(page)
        raise EffortNotFound(want, seen)

    # 回读复验：滑块是异步更新的，不复验就可能把「还没生效」当成功。
    settled = _effort_state(page)["label"]
    if settled not in wants:
        _escape(page)
        raise CdpError(f"档位没设上：要 {want}，滑块停在 {settled}")
    _escape(page)
    return {"model": model, "effort_actual": settled, "available": seen, "touched": True}


def _js_str(s):
    import json as _json
    return _json.dumps(s, ensure_ascii=False)


# ---------------------------------------------------------------- 正文

# 附件 chip 的锚点。用可见文案（定位优先级 ②）——这个卡片上没有 data-testid，
# 里面唯一的按钮就是「在文本字段中显示」。文案变了会退化成 0，
# 下面的「附件数必须 +1」校验会立刻发现，不会静默放行。
_CHIPS_JS = """
    const _form = document.querySelector('#prompt-textarea').closest('form') || document.body;
    const _hit = e => /在文本字段中显示|Show in text field/.test(e.textContent);
    const chips = () => [..._form.querySelectorAll('*')]
        .filter(e => _hit(e) && ![...e.children].some(_hit)).length;
"""

# 量「会被发出去的文本」，不是量渲染结果。
# ChatGPT 会把粘进来的 URL 转成 inline selection pill（一个 contenteditable=false 的
# <span>，完整 URL 存在 data-id 里，显示时藏掉 scheme+host 并另起一行）。
# 于是 innerText 比原文短——2026-08-22 实测一条 GitHub 链接就少 18 字，
# 正好顶穿容差，把一发完全正常的提交判成注入失败。
# 另外整段正文只落在一个 <p> 里，换行是 <br>，所以不能按段落切。
_TEXT_JS = r"""
    const _logical = () => {
        const el = document.querySelector('#prompt-textarea');
        if (!el) return '';
        const out = [];
        const walk = n => {
            if (n.nodeType === 3) { out.push(n.data); return; }
            if (n.nodeType !== 1) return;
            if (n.tagName === 'BR') { out.push('\n'); return; }
            if (n.hasAttribute('data-inline-selection-pill'))
                { out.push(n.getAttribute('data-id') || n.innerText); return; }
            const block = /^(P|DIV|LI|BLOCKQUOTE|PRE|H[1-6])$/.test(n.tagName);
            if (block && out.length && !out[out.length - 1].endsWith('\n')) out.push('\n');
            [...n.childNodes].forEach(walk);
        };
        [...el.childNodes].forEach(walk);
        return out.join('');
    };
"""

_PASTE_JS = """
    const el = document.querySelector('#prompt-textarea');
    if (!el) return {ok: false, why: 'no_composer'};
""" + _TEXT_JS + _CHIPS_JS + """
    const before = document.querySelectorAll('[data-message-author-role]').length;
    const chips_before = chips();
    el.focus();
    if (ARG.clear) { document.execCommand('selectAll'); document.execCommand('delete'); }
    const dt = new DataTransfer();
    dt.setData('text/plain', ARG.text);
    el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));

    // 不是 sleep 后拍一张照：超长正文转附件要走「清空 composer → 建附件 → chip 出现 →
    // 可发送」好几步，固定等待会采样到中间态。这里轮询到形态稳定为止。
    const want = ARG.text.trim().length;
    const deadline = Date.now() + ARG.budget;
    let last = null, stable = 0;
    while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 250));
        const now = {len: _logical().trim().length, chips: chips()};
        const settled = (now.len >= want * 0.99) || (now.len === 0 && now.chips > chips_before);
        if (last && now.len === last.len && now.chips === last.chips) {
            if (++stable >= 2 && settled) break;
        } else { stable = 0; }
        last = now;
    }
    const sendBtn = document.querySelector('[data-testid="send-button"]');
    return {ok: true, len: _logical().trim().length,
            inner_len: el.innerText.trim().length,
            chips_before: chips_before, chips_after: chips(),
            send_enabled: sendBtn ? !sendBtn.disabled : null,
            msgs_delta: document.querySelectorAll('[data-message-author-role]').length - before};
"""

# 清残留附件：selectAll+delete 只清 composer，**清不掉附件**（2026-08-21 实测）。
# 附件卡片上没有移除键，唯一的出路是点「在文本字段中显示」把它还原成内联文本再删。
_DROP_CHIPS_JS = """
""" + _TEXT_JS + _CHIPS_JS + """
    const el = document.querySelector('#prompt-textarea');
    for (let i = 0; i < 6 && chips() > 0; i++) {
        const btn = [..._form.querySelectorAll('button,[role=button]')].find(
            b => /在文本字段中显示|Show in text field/.test(b.getAttribute('aria-label') || b.innerText || ''));
        if (!btn) break;
        btn.click();
        await new Promise(r => setTimeout(r, 1500));
        el.focus(); document.execCommand('selectAll'); document.execCommand('delete');
        await new Promise(r => setTimeout(r, 500));
    }
    el.focus(); document.execCommand('selectAll'); document.execCommand('delete');
    return {chips: chips(), composer: _logical().trim().length};
"""


# ---------------------------------------------------------------- 上传附件
#
# 上传件和「超长粘贴自动转的附件卡片」是**两套 UI**：chips() 那套认的是
# 「在文本字段中显示」的卡片，数上传件一律是 0。别把两者混用。
#
# 锚点用每张卡片上的移除按钮：aria-label 形如「移除文件1：a.png」
# （英文界面是 Remove file 1: ...）。这是定位优先级①的 a11y name；
# 卡片本身只有 tailwind 生成的 class，改版必变，不能用。
_UPLOADS_JS = """
    const _upBtns = () => [...document.querySelectorAll('button,[role=button]')]
        .filter(b => /^(移除文件|Remove file)/.test(b.getAttribute('aria-label') || ''));
    const _upNames = () => _upBtns().map(
        b => (b.getAttribute('aria-label') || '').replace(/^(移除文件|Remove file)\s*\d*\s*[:：]\s*/, ''));
    // 注意：卡片里那个转圈**不能**当就绪判据。实测它在上传完成之后才出现
    // （卡片先转圈消失 →3s→ 又回来），而且长期不消失；带着它按发送照样能发出去
    // （实测 1s 拿到 URL）。它是上传完成后的二次处理指示，不是「还没传完」。
"""

# 文件输入框：ChatGPT 有三个 input[type=file]，#upload-photos / #upload-camera
# 限 image/*，只有通吃的那个 accept 为空。挑 accept 最宽的那个——这样支持什么
# 由 ChatGPT 服务端决定，我们不自己维护一张类型白名单。
_FILE_INPUT = ("[...document.querySelectorAll('input[type=file]')]"
               ".sort((a, b) => (a.accept ? 1 : 0) - (b.accept ? 1 : 0))[0]")

MAX_ATTACHMENTS = 10          # ChatGPT 单条消息的上限，先拦住免得白等一场


def count_uploads(page):
    return page.evaluate("(() => {" + _UPLOADS_JS + " return _upBtns().length; })()", timeout=20)


def upload_names(page):
    return page.evaluate("(() => {" + _UPLOADS_JS + " return _upNames(); })()", timeout=20) or []


def drop_uploads(page, timeout=30):
    """清掉输入框里遗留的上传件。返回清完之后还剩几个。

    和遗留附件卡片同样的道理：留着不清就会把上一个作业的文件一起发出去，
    而且还返回成功。这里只点每张卡片自己的移除键，不碰别的控件。
    """
    return page.evaluate("(async () => {" + _UPLOADS_JS + """
        for (let i = 0; i < 12 && _upBtns().length; i++) {
            _upBtns()[0].click();
            await new Promise(r => setTimeout(r, 400));
        }
        return _upBtns().length;
    })()""", timeout=timeout)


def attach_files(page, paths, timeout=180):
    """把本地文件传进输入框，确认全部就位后才返回。

    走 DOM.setFileInputFiles 而不是点「添加文件」——那会弹原生文件选择框，
    CDP 够不着，一弹就把整条自动化堵死。

    上传是异步的：塞进去之后卡片要等服务端回执才出现（实测数秒）。
    所以只认「卡片数正好 +N 且连续两次读数一致」，不用固定 sleep。
    发送按钮不能当就绪信号——它在上传开始前就是可用的（实测 t=1s 即 True）。

    就绪判据只有两条：卡片数正好 +N 且连续两次稳定，加上文件名对得上。
    别拿卡片里的转圈当判据——见 _UPLOADS_JS 里的注释，那是上传完成之后
    才出现的二次处理指示，长期不灭，用它当判据会把好端端的附件判成没传完。
    """
    if len(paths) > MAX_ATTACHMENTS:
        raise CdpError(f"一次最多 {MAX_ATTACHMENTS} 个附件，给了 {len(paths)} 个")
    left = drop_uploads(page)
    if left:
        raise CdpError(f"输入框里有清不掉的遗留上传件（{left} 个），"
                       "拒绝在脏页面上提交——否则会把别人的文件一起发出去")
    want = len(paths)
    page.set_file_input(_FILE_INPUT, paths)

    deadline = time.time() + timeout
    stable = last = 0
    while time.time() < deadline:
        time.sleep(1)
        n = count_uploads(page)
        stable = stable + 1 if n == last else 0
        last = n
        if n >= want and stable >= 2:
            break
    else:
        raise CdpError(f"等待超时（{timeout}s）：上传件只就位 {last}/{want} 个")
    if last != want:
        raise CdpError(f"上传件数量对不上：就位 {last} 个，期望 {want} 个")

    # 名字也核一遍。ChatGPT 会给重名文件加 (1) 后缀，所以只比对主干。
    got = upload_names(page)
    missing = [Path(p).name for p in paths
               if not any(Path(p).stem in g for g in got)]
    if missing:
        raise CdpError(f"上传件名字对不上，缺：{missing}（页面上是 {got}）")
    return {"count": last, "names": got}


def count_chips(page):
    return page.evaluate("(() => {" + _CHIPS_JS + " return chips(); })()", timeout=20)


def drop_chips(page):
    """清掉输入框里遗留的附件。返回清完之后还剩几个。"""
    return page.call_fn(_DROP_CHIPS_JS.replace("ARG", "null"), None, timeout=60)


def _paste(page, text, clear, budget=20000, timeout=90):
    got = page.call_fn(_PASTE_JS, {"text": text, "clear": clear, "budget": budget},
                       timeout=timeout)
    if not got.get("ok"):
        raise CdpError(f"正文注入失败：{got.get('why')}")
    if got.get("msgs_delta"):
        raise CdpError(
            f"正文注入过程中冒出了 {got['msgs_delta']} 条新消息，疑似提前发送，已停止")
    return got


def inject(page, text, tail=None):
    """走 paste 事件写入 composer。

    绝不能用键盘输入：ChatGPT 的 composer 是 Enter 发送，多行正文会在第一个换行处
    把半截内容发出去，然后继续往下敲、继续发。

    **超过约 8000~10000 字的粘贴，ChatGPT 会自动转成附件**（输入框里出现
    「在文本字段中显示」的 chip，innerText 为空）。这是正常路径不是失败 ——
    2026-08-21 有两个真实作业（727KB / 144KB 正文）就是被旧代码的
    「注入 0 vs 期望 406929」判死的。走附件时把 tail（输出格式要求）另贴一段进输入框，
    免得格式指令一起沉进附件里。

    不预判阈值、只看实际落地形态：阈值是 ChatGPT 定的，哪天改了这里照样能走。

    ⚠️ 附件会**累加**且 selectAll+delete 清不掉（实测）。所以粘贴前必须先清干净，
    粘贴后只认「附件数正好 +1」—— 只看「有没有 chip」的话，上一个作业遗留的附件
    会被当成本次的，下一个作业带着别人的上下文发出去还返回成功。
    这种静默发错上下文比直接报错严重得多。
    """
    text = text.strip()
    left = drop_chips(page)
    if left.get("chips"):
        raise CdpError(f"输入框里有清不掉的遗留附件（{left['chips']} 个），"
                       "拒绝在脏页面上提交——否则会把别人的上下文一起发出去")

    got = _paste(page, text, clear=True)
    want = len(text)
    added = got["chips_after"] - got["chips_before"]

    if abs(got["len"] - want) <= max(8, want * 0.002):
        if added:
            raise CdpError(f"正文按内联进去了，但同时多出 {added} 个附件，形态不干净")
        got["mode"] = "inline"
        return got

    if added == 1 and got["len"] == 0:
        got["mode"] = "attachment"
        got["requested_chars"] = want      # 只是"投进去多少"，不等于"附件里验到多少"
        if tail:
            t = _paste(page, tail, clear=False, budget=8000)
            if t["len"] < max(8, len(tail.strip()) * 0.5):
                raise CdpError(f"附件已就位，但输出格式要求没贴进输入框（落入 {t['len']} 字）")
            if t["chips_after"] != got["chips_after"]:
                raise CdpError(f"贴输出格式要求之后附件数变了"
                               f"（{got['chips_after']} → {t['chips_after']}），已停止")
            got["len"] = t["len"]
            got["send_enabled"] = t["send_enabled"]
            got["tail_inline"] = True
        if not got.get("send_enabled"):
            raise CdpError("正文转成了附件，但发送按钮仍不可用")
        return got

    raise CdpError(f"正文注入形态不对：落入 {got['len']} 字 / 期望 {want} 字，"
                   f"附件数 {got['chips_before']} → {got['chips_after']}"
                   f"（内联和附件两条路都没走通）")


class SendNotTaken(CdpError):
    """点了发送但页面没有任何反应——**确证没发出去**，重跑是安全的。"""


def send(page, confirm=12):
    """点发送，并确认它真的生效了。

    只点不验的代价：2026-08-26 一个 Pro 档作业带附件提交，点击没落到实处，
    然后只能干等 URL 超时，最后报 send_unknown——事后人工去翻标签页才确认
    「0 条消息、草稿还在」，也就是压根没发。那次白等 60 秒还留下个要人工裁决的作业。

    发送生效的**本地**信号是输入框被清空（比 URL 变化早得多，也不受
    Pro 档长思考影响）。清空了就认；到点还原样不动，那就是确证没发出去。

    ⚠️ 重试那一下必须重新定位元素，**绝不能照着缓存坐标再点**：
    发送成功后按钮会**原地变成 stop**。拿旧坐标补一刀，点到的就是 stop，
    等于自己把刚发出去的生成掐断，而且看起来像「发送失败」。
    所以下面每一个「已发出去」的证据里都包含 stop 按钮的出现，
    只有全部证据都不成立、且 send 按钮还在，才允许换一种方式再点一次。
    """
    _SENT_JS = """(() => {
        const el = document.querySelector('#prompt-textarea');
        return JSON.stringify({
            len: el ? el.innerText.trim().length : -1,
            users: document.querySelectorAll('[data-message-author-role=user]').length,
            url: location.pathname,
            stop: !!document.querySelector('[data-testid="stop-button"]'),
            send: !!document.querySelector('[data-testid="send-button"]')});
    })()"""

    # 判据一律跟点击前的基线比，不能用绝对值：续聊时 URL 本来就是 /c/...、
    # 本来就有用户消息，用绝对判据的话点击之前就"已发送"，校验形同虚设。
    base = json.loads(page.evaluate(_SENT_JS, timeout=20))
    before = base["len"]

    def _sent(st):
        # 任意一条成立就说明这一发已经出去了，绝不能再点。
        # 前两条是持久信号（发出去之后一直成立），后两条是瞬时的，
        # 极速档三秒就生成完、stop 会变回 send，所以不能只靠它们。
        return (st["len"] == 0 or st["url"] != base["url"]
                or st["users"] > base["users"]
                or (st["stop"] and not base["stop"])
                or (base["send"] and not st["send"]))
    page.click_js("document.querySelector('[data-testid=\"send-button\"]')", "发送按钮")
    if before <= 0:
        return                      # 输入框本来就空，验不了，也就不敢重试

    def _wait(sec):
        end = time.time() + sec
        st = None
        while time.time() < end:
            time.sleep(0.5)
            st = json.loads(page.evaluate(_SENT_JS, timeout=20))
            if _sent(st):
                return True, st
        return False, st

    ok, st = _wait(confirm)
    if ok:
        return

    # 到这里五条证据都不成立：输入框内容没动、没有新消息、URL 没变、
    # 没有 stop 按钮、send 按钮还在。也就是确证什么都没发生，补一刀是安全的。
    #
    # 残余竞态：这五条都是渲染层现象，请求已经发出但 DOM 还没更新的那一小段
    # 里会误判成「没发」。实测 DOM 在 0.5s 内就更新（输入框清空、stop 出现、
    # URL 变 /c/WEB:），这里等 12s 才动手，留了二十多倍余量。
    # Resource Timing 记不到这个请求（实测发送前后条目数不变），要做到真正
    # 无竞态得订阅 CDP 的 Network 事件——那要改传输层，暂未做。
    #
    # 补刀前再看最后一眼：把「最后一次轮询」到「点击」之间的空隙也收掉。
    final = json.loads(page.evaluate(_SENT_JS, timeout=20))
    if _sent(final):
        return
    # 换页内事件派发——坐标点击在后台标签页上偶尔会丢。
    # 用 cdp 里那套完整指针序列，**不要用裸 el.click()**：ChatGPT 的按钮是
    # React 组件，行为绑在 pointerdown/mousedown 上，只发一个 click 事件不触发。
    # 这里用选择器当场重新定位，绝不用之前那次的坐标（那个位置现在可能是 stop）。
    page.evaluate("(() => { const b = document.querySelector('[data-testid=\"send-button\"]');"
                  f" return b ? {cdp.Page._JS_CLICK}(b) : false; }})()", timeout=20)
    ok, st = _wait(confirm)
    if ok:
        return
    raise SendNotTaken(
        f"点了两次发送（坐标 + 页内派发），{confirm * 2}s 内输入框仍是 {st['len']} 字、"
        "没有新消息、没有 stop 按钮——确证没发出去")


CONV_URL_JS = """(() => {
  const m = location.pathname.match(/^\\/c\\/(.+)$/);
  return m && !m[1].startsWith('WEB:') ? location.href : null;
})()"""


def wait_conversation_url(page, timeout=60):
    """等服务端真 id。发送后会先短暂停在 /c/WEB:<临时id>，那个 URL 事后打不开。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = page.evaluate(CONV_URL_JS)
        if url:
            return url
        time.sleep(0.5)
    raise CdpError(f"等待对话 URL 超时（{timeout}s），当前 {page.url()}")


# ---------------------------------------------------------------- 读结果

_PROGRESS_JS = """(() => {
  const a = document.querySelectorAll('[data-message-author-role="assistant"]');
  const last = a[a.length - 1];
  const t = last ? last.innerText : '';
  return {
    url: location.href,
    generating: !!document.querySelector('[data-testid="stop-button"]'),
    assistant_msgs: a.length,
    user_msgs: document.querySelectorAll('[data-message-author-role="user"]').length,
    // 结构探针：这两个锚点是「页面还是我们认识的样子」的证据。
    // 没有它们时，stop-button 缺失只能说明「选择器可能变了」，不能推出「生成完了」。
    has_composer: !!document.querySelector('#prompt-textarea'),
    has_send_btn: !!document.querySelector('[data-testid="send-button"]'),
    len: t.length,
    tail: t.slice(-1200),
  };
})()"""

_FULL_JS = """(() => {
  const a = document.querySelectorAll('[data-message-author-role="assistant"]');
  const last = a[a.length - 1];
  return last ? last.innerText : '';
})()"""


def count_assistant(page):
    return page.evaluate("document.querySelectorAll('[data-message-author-role=\"assistant\"]').length")


def wait_new_turn(page, before, timeout=90):
    """续聊场景下确认「这一发真的出去了」。

    新开会话可以靠 URL 从 / 变成 /c/<id> 来确认；续聊时 URL 压根不变，
    wait_conversation_url 会立刻返回，等于没检查。这里改看真实证据：
    助手消息数增加，或者生成中的停止按钮出现。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = page.evaluate(
            "(() => ({n: document.querySelectorAll('[data-message-author-role=\"assistant\"]').length,"
            " gen: !!document.querySelector('[data-testid=\"stop-button\"]')}))()")
        if st["n"] > before or st["gen"]:
            return st
        time.sleep(0.5)
    raise CdpError(f"发送后 {timeout}s 内没看到新回合（助手消息数仍为 {before}，也没有生成中标志）")


def read_progress(page):
    return page.evaluate(_PROGRESS_JS)


def read_full(page):
    return page.evaluate(_FULL_JS, timeout=120)


def attach_or_open(page_id, conversation_url, timeout=PAGE_TIMEOUT):
    """优先复用 submit 时那个标签页；被关掉了就用 conversation_url 重开一个。"""
    if page_id:
        try:
            page = cdp.attach(page_id)
            guard_host(page)
            return page, page_id, False
        except CdpError:
            pass
    if not conversation_url:
        raise CdpError("既没有可用标签页，job.json 里也没有 conversation_url")
    page, target_id = cdp.open_page(conversation_url, timeout=timeout)
    try:
        guard_host(page)
        # 会话内容是异步渲染的。刚打开就读会拿到 0 条消息 + 无停止按钮，
        # 看起来跟「已完成但没输出」一模一样，会误判。
        _wait(page, "document.querySelectorAll('[data-message-author-role]').length > 0",
              "会话消息渲染", timeout=timeout)
    except Exception:
        page.close()          # 只断 WS，标签页留着给人看现场
        raise
    return page, target_id, True
