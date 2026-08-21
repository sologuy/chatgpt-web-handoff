"""raw CDP 驱动 —— 纯 stdlib，零第三方依赖。

只做传输与通用页面操作，不含任何 ChatGPT 业务逻辑（那部分在 bin/cgh 里）。
连 127.0.0.1:9222 上用户日常那个 Chrome，与 chrome-devtools MCP 走同一个端口。
"""

import base64
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

HOST = "127.0.0.1"
PORT = 9222


class CdpError(Exception):
    pass


# ---------------------------------------------------------------- HTTP 探活


def http_json(path, method="GET", timeout=5):
    url = f"http://{HOST}:{PORT}{path}"
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise CdpError(f"连不上 {HOST}:{PORT} —— {e}")
    return json.loads(body) if body.strip() else None


def browser_version():
    return http_json("/json/version")


def list_pages():
    return [t for t in (http_json("/json/list") or []) if t.get("type") == "page"]


# ---------------------------------------------------------------- WebSocket


class _WS:
    """够用的 WebSocket 客户端：文本帧、分片重组、ping/pong。"""

    def __init__(self, url, timeout=60):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=10)
        self.sock.settimeout(timeout)
        path = u.path + (f"?{u.query}" if u.query else "")
        key = base64.b64encode(os.urandom(16)).decode()
        hs = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {u.hostname}:{u.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(hs.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CdpError("WS 握手失败：连接被对端关闭")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        status = head.split(b"\r\n")[0]
        if b" 101" not in status:
            raise CdpError(f"WS 握手失败：{status.decode('utf-8', 'replace')}")
        self._rx = rest

    def _exact(self, n):
        while len(self._rx) < n:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise CdpError("WS 连接已关闭")
            self._rx += chunk
        out, self._rx = self._rx[:n], self._rx[n:]
        return out

    def _frame(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, text):
        self._frame(0x1, text.encode("utf-8"))

    def recv(self):
        parts = []
        while True:
            b0, b1 = self._exact(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exact(8))[0]
            data = self._exact(n) if n else b""
            if opcode == 0x9:            # ping → 回 pong
                self._frame(0xA, data)
                continue
            if opcode == 0xA:            # pong
                continue
            if opcode == 0x8:
                raise CdpError("WS 被对端关闭")
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self._frame(0x8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------- 会话


class Session:
    """一条 CDP 连接（浏览器级或页面级）。"""

    def __init__(self, ws_url, timeout=60):
        self.ws = _WS(ws_url, timeout)
        self._id = 0

    def call(self, method, params=None, timeout=60):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") != mid:
                continue                  # 事件通知，本项目不订阅，直接丢
            if "error" in msg:
                raise CdpError(f"{method} 失败：{msg['error'].get('message')}")
            return msg.get("result", {})
        raise CdpError(f"{method} 超时（{timeout}s）")

    def close(self):
        self.ws.close()


_DEAD = {"vis": None, "focus": False, "raf": False, "timer": False}


class Page(Session):
    """页面级会话：JS 求值 + 真实鼠标事件。"""

    def evaluate(self, expression, timeout=60):
        r = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout,
        )
        if "exceptionDetails" in r:
            desc = r["exceptionDetails"].get("exception", {}).get("description")
            raise CdpError(f"JS 异常：{desc or json.dumps(r['exceptionDetails'], ensure_ascii=False)}")
        return r.get("result", {}).get("value")

    def call_fn(self, body, arg=None, timeout=60):
        """把 arg 以 JSON 字面量注入函数体求值，规避一切转义问题。"""
        literal = json.dumps(arg, ensure_ascii=False)
        return self.evaluate(f"(async (ARG) => {{{body}}})({literal})", timeout)

    def unfreeze(self, check=True):
        """让后台标签页照常渲染，并自检确实生效了。

        Chrome 会冻结/节流不可见的标签页：ChatGPT 的流式回答虽然收到了，
        DOM 却不更新（实测卡在 5 个字，解冻后瞬间跳到 4243）。轮询读到的
        就是冻住的旧内容，接着会被判成「生成停了」。
        这两个开关让页面以为自己可见且有焦点，从而免掉「把标签页调到前台」。

        两个开关作用边界不同，都要留：前者解除页面生命周期 frozen，
        后者模拟 focused/active。**做完必须自检**——这两个是 experimental CDP API，
        Chrome 换个版本语义就可能变；不自检的话失效了也不报错，
        表现成「回答永远只有 5 个字」「菜单永远点不开」这类查不出来的怪事。

        check=False 用于新建 target：两个开关要赶在导航开始前施加，
        但那会儿还没有执行上下文，自检得推迟到页面加载完再补做。
        """
        for method, params in (("Page.setWebLifecycleState", {"state": "active"}),
                               ("Emulation.setFocusEmulationEnabled", {"enabled": True})):
            try:
                self.call(method, params)
            except CdpError:
                pass          # 老版本 Chrome 可能没有，留给下面的自检去判
        if not check:
            return None

        if not check:
            return None
        return self._verify_awake()

    def _verify_awake(self, budget=30):
        """反复探到通过为止，探不通才判失败。

        单次探测不能当判决：页面跑长主线程任务时（ChatGPT 刚加载完那阵最典型），
        连 setTimeout 都被挡住，探针会超时——那是"页面忙"，不是"页面冻住了"。
        一次失败就终止作业等于把假阴性做成了故障。

        budget 是**整次自检的绝对总预算**，每次探测都按剩余时间收窄。
        不这么做的话，快探超时 + evaluate 超时 + socket 超时会逐层累加，
        实测最坏要 42s 才判定——多层 timeout 相乘是没有上界的。
        """
        deadline = time.time() + budget
        awake = None
        while True:
            awake = self._awake_probe(1500, deadline)
            if awake and awake.get("raf") and awake.get("timer"):
                break
            if time.time() >= deadline:
                break
            # 重新施加一次再宽限地探——override 可能是真丢了，也可能只是页面忙
            for method, params in (("Page.setWebLifecycleState", {"state": "active"}),
                                   ("Emulation.setFocusEmulationEnabled", {"enabled": True})):
                try:
                    self.call(method, params)
                except CdpError:
                    pass
            awake = self._awake_probe(5000, deadline)
            if awake and awake.get("raf") and awake.get("timer"):
                break
            if time.time() >= deadline:
                break
            time.sleep(1)

        if (not awake or awake.get("vis") != "visible" or not awake.get("focus")
                or not awake.get("raf") or not awake.get("timer")):
            raise CdpError(
                f"后台标签页解冻失败（visibilityState={awake and awake.get('vis')}, "
                f"hasFocus={awake and awake.get('focus')}, rAF={awake and awake.get('raf')}, "
                f"timer={awake and awake.get('timer')}）"
                "——页面会停止渲染，读到的进度都是冻住的旧值")
        return awake

    _PROBE = """(async (MS) => {
      const frames = new Promise(r => {
        let n = 0;
        const t = setTimeout(() => r(false), MS);
        const step = () => (++n >= 2) ? (clearTimeout(t), r(true)) : requestAnimationFrame(step);
        requestAnimationFrame(step);
      });
      const timer = new Promise(r => {
        const t = setTimeout(() => r(false), MS);
        setTimeout(() => (clearTimeout(t), r(true)), 0);
      });
      return {vis: document.visibilityState, focus: document.hasFocus(),
              raf: await frames, timer: await timer};
    })"""

    def _awake_probe(self, ms, deadline=None):
        """rAF 连测两帧 + 一个宏任务心跳。两者都通才算 scheduler 真的在跑。

        单帧 rAF 分不清「刚好赶上一帧」和「持续在跑」；只看 rAF 也分不清
        「渲染被节流」和「整个页面被冻住」——后者连 setTimeout 都不走。
        页面被彻底冻住时 JS 根本不执行，这里会超时，同样按解冻失败论。
        """
        wait = ms / 1000.0 + 8
        if deadline is not None:
            left = deadline - time.time()
            if left <= 0:
                return _DEAD
            wait = min(wait, left)
            ms = min(ms, max(200, (wait - 0.5) * 1000))   # 留 0.5s 给往返
        try:
            return self.evaluate(f"{self._PROBE}({int(ms)})", timeout=wait)
        except (CdpError, OSError):
            # OSError 包含 socket 超时：页面彻底冻住时 evaluate 永不返回，
            # 底层 recv 先超时抛裸异常，只捕 CdpError 会漏掉这条最要命的路径。
            # 探针跑不动可能是真冻住，也可能只是主线程正忙。
            # 这里不下结论，返回全 false 让 _verify_awake 的预算去判。
            return _DEAD

    def url(self):
        return self.evaluate("location.href")

    def host(self):
        return self.evaluate("location.host")

    # -- 鼠标 ------------------------------------------------------------

    def click_point(self, x, y):
        """派发真实鼠标事件（Radix 等库依赖 trusted event，JS .click() 不可靠）。"""
        base = {"x": x, "y": y, "button": "left", "clickCount": 1}
        self.call("Input.dispatchMouseEvent", dict(base, type="mouseMoved", button="none", clickCount=0))
        self.call("Input.dispatchMouseEvent", dict(base, type="mousePressed"))
        self.call("Input.dispatchMouseEvent", dict(base, type="mouseReleased"))

    def hit_point(self, finder_js):
        """返回该元素真正可点的坐标；不可点返回 None。

        「在 DOM 里」不等于「能点」：ChatGPT 的菜单把折叠内容留在 DOM 里、用
        overflow:clip 裁掉，此时元素照样有非零 rect，但那个坐标上最上层是菜单
        底下的页面。照着点既点不到目标，还会把菜单点关。所以必须做命中测试。
        """
        # 只在元素确实在视口外时才 scrollIntoView。无条件滚会把下拉菜单
        # （overflow:auto 的小容器）滚得每次探测都换位置，坐标永远稳定不下来。
        return self.evaluate(
            "(() => { const el = (" + finder_js + "); if (!el) return null;"
            " let r = el.getBoundingClientRect();"
            " if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) {"
            "   el.scrollIntoView({block:'center'}); r = el.getBoundingClientRect(); }"
            " if (!r.width || !r.height) return null;"
            " const x = r.left + r.width/2, y = r.top + r.height/2;"
            " if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return null;"
            " const top = document.elementFromPoint(x, y);"
            " if (!top || !(top === el || el.contains(top))) return null;"
            " return {x, y}; })()"
        )

    def hittable(self, finder_js):
        return self.hit_point(finder_js) is not None

    def wait_hittable(self, finder_js, what="元素", timeout=15, stable=True):
        """等到元素可命中；stable=True 还要求坐标连续两次读数一致。

        命中测试和实际点击之间隔着两三个 CDP 往返。菜单展开动画期间元素一直在动，
        「测的时候能命中」不等于「点下去还在原地」——不等稳定就会点空。
        """
        deadline = time.time() + timeout
        prev = None
        while time.time() < deadline:
            box = self.hit_point(finder_js)
            if box:
                if not stable:
                    return box
                if prev and abs(box["x"] - prev["x"]) < 2 and abs(box["y"] - prev["y"]) < 2:
                    return box
                prev = box
            else:
                prev = None
            time.sleep(0.25)
        raise CdpError(f"定位失败：{what}")

    # 后台标签页（visibilityState=hidden）没有合成帧，Input.dispatchMouseEvent 的坐标
    # 命中在浏览器进程侧会失败——事件哪儿都不到，元素连 pointerdown 都收不到。
    # 这种页只能在渲染进程里直接往元素上派发事件序列。Radix 之类的库看的是
    # pointerdown/click 有没有到，不检查 isTrusted，所以合成事件够用。
    _JS_CLICK = """(el => {
      const r = el.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      const base = {bubbles: true, cancelable: true, composed: true,
                    clientX: x, clientY: y, button: 0,
                    pointerId: 1, pointerType: 'mouse', isPrimary: true};
      const P = (t, o) => el.dispatchEvent(new PointerEvent(t, {...base, ...o}));
      const M = (t, o) => el.dispatchEvent(new MouseEvent(t, {...base, ...o}));
      P('pointerover', {buttons: 0}); P('pointerenter', {buttons: 0});
      P('pointermove', {buttons: 0}); M('mousemove', {buttons: 0});
      P('pointerdown', {buttons: 1}); M('mousedown', {buttons: 1});
      P('pointerup', {buttons: 0});   M('mouseup', {buttons: 0});
      M('click', {buttons: 0});
      return true;
    })"""

    def click_js(self, finder_js, what="元素", timeout=15):
        """点元素的可视中心。自带等待重试——ChatGPT 的 composer 与菜单都是分批渲染的，
        打一次就放弃会把「还没渲染完」误报成「UI 改版了」。

        页面可见时用真实鼠标事件（最贴近用户行为）；页面在后台时改用页内事件派发，
        否则点击会静默丢失。不为此把标签页调到前台——那会打断用户。
        """
        box = self.wait_hittable(finder_js, what, timeout)
        if self.evaluate("document.visibilityState") == "hidden":
            self.evaluate(f"(() => {{ const el = ({finder_js}); "
                          f"return el ? {self._JS_CLICK}(el) : false; }})()")
        else:
            self.click_point(box["x"], box["y"])
        return box


# ---------------------------------------------------------------- 页面管理


def _page_ws(target_id):
    for _ in range(20):
        for p in list_pages():
            if p.get("id") == target_id and p.get("webSocketDebuggerUrl"):
                return p["webSocketDebuggerUrl"]
        time.sleep(0.2)
    raise CdpError(f"新标签页 {target_id} 未出现在 /json/list")


def open_page(url, timeout=60, background=True):
    """新开标签页并返回 (Page, target_id)。走浏览器级 Target.createTarget，比 PUT /json/new 稳。

    默认后台创建：这是用户日常在用的 Chrome，不抢焦点、不闪标签页。
    """
    ver = browser_version()
    ws_url = ver.get("webSocketDebuggerUrl")
    if not ws_url:
        raise CdpError("/json/version 没有 webSocketDebuggerUrl，Chrome 未开远程调试？")
    browser = Session(ws_url)
    try:
        params = {"url": url, "background": background}
        try:
            target_id = browser.call("Target.createTarget", params)["targetId"]
        except CdpError:
            params.pop("background")          # 老版本 Chrome 不认 background
            target_id = browser.call("Target.createTarget", params)["targetId"]
    finally:
        browser.close()
    page = Page(_page_ws(target_id))
    page.call("Page.enable")
    page.call("Runtime.enable")
    page.unfreeze(check=False)         # 赶在导航前施加；自检等加载完再做
    # 新 target 刚建出来时还停在 about:blank，readyState 就已经是 complete。
    # 只等 readyState 会拿到空 host，让调用方的白名单校验误判成「页面不对」。
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = page.evaluate("[document.readyState, location.host]")
        if state and state[1] and state[0] in ("interactive", "complete"):
            # 导航会重置 override，这里重新施加一次。
            # 但**不自检**：页面刚加载完正在跑 bundle，长主线程任务会把探针挡住，
            # 探出来的 false 是"忙"不是"冻"。自检留给 attach() 和 composer 就绪之后。
            page.unfreeze(check=False)
            return page, target_id
        time.sleep(0.3)
    raise CdpError(f"页面 {url} 在 {timeout}s 内未完成导航（当前 {page.evaluate('location.href')}）")


def attach(target_id):
    page = Page(_page_ws(target_id))
    page.unfreeze()
    return page


def close_target(target_id):
    ws_url = browser_version().get("webSocketDebuggerUrl")
    if not ws_url:
        return
    browser = Session(ws_url)
    try:
        browser.call("Target.closeTarget", {"targetId": target_id})
    except CdpError:
        pass
    finally:
        browser.close()
