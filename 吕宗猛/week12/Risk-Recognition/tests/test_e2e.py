# -*- coding: utf-8 -*-
"""
楼道消防风险识别 —— 前端端到端测试（可复现）

用 Chrome DevTools Protocol 驱动真实浏览器，覆盖两条用户路径：
  1. 上传链路：把图片注入 <input type=file> -> change 事件 -> 压缩 -> 提交 -> 结果卡片
  2. 拍照链路：Chrome 假摄像头设备（--use-fake-device-for-media-stream）
                -> getUserMedia -> canvas 截帧 -> 提交 -> 结果卡片

前置：后端已启动（默认 http://127.0.0.1:8000），且本机安装了 Chrome。
用法：python tests/test_e2e.py
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHROME = os.environ.get("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
BASE = os.environ.get("CORRIDOR_PAGE", "http://127.0.0.1:8000/")
ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "tests" / "samples"
PROFILE = ROOT / "tests" / ".chrome-profile"
OUT_JSON = ROOT / "tests" / "e2e_result.json"
OUT_PNG = ROOT / "tests" / "e2e_result.png"

PORT = 9337


class WS:
    """最小 CDP WebSocket 客户端（标准库实现）。"""

    def __init__(self, url):
        from urllib.parse import urlparse
        u = urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.buf = b""
        self.id = 0

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise EOFError("connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, method, params=None, timeout=120):
        self.id += 1
        mid = self.id
        payload = json.dumps({"id": mid, "method": method, "params": params or {}}).encode()
        mask = os.urandom(4)
        n = len(payload)
        hdr = bytearray([0x81])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126); hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127); hdr += struct.pack(">Q", n)
        hdr += mask
        hdr += bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.s.sendall(hdr)
        deadline = time.time() + timeout
        while time.time() < deadline:
            h = self._read(2)
            op, ln = h[0] & 0x0F, h[1] & 0x7F
            masked = h[1] & 0x80
            if ln == 126:
                ln = struct.unpack(">H", self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read(8))[0]
            mk = self._read(4) if masked else None
            data = self._read(ln)
            if mk:
                data = bytes(b ^ mk[i % 4] for i, b in enumerate(data))
            if op == 0x9:
                self.s.sendall(b"\x8a\x80" + os.urandom(4)); continue
            if op == 0x8:
                raise EOFError("connection closed")
            if op in (0x1, 0x2):
                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception:
                    continue
                if msg.get("id") == mid:
                    return msg
        raise TimeoutError(method)

    def eval(self, expr, timeout=120):
        r = self.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout)
        if "exceptionDetails" in r.get("result", {}):
            return {"__error__": str(r["result"]["exceptionDetails"])[:300]}
        return r.get("result", {}).get("result", {}).get("value")


def launch(extra_args):
    PROFILE.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
         f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}",
         "--remote-allow-origins=*", "--window-size=430,932", BASE] + extra_args,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def attach():
    for _ in range(40):
        try:
            targets = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/json/list", timeout=10).read())
            page = next((t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
            if page:
                return WS(page["webSocketDebuggerUrl"])
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("无法连接 Chrome CDP")


RESULT_JS = """(()=>{
  const r=document.getElementById('result'), e=document.getElementById('err');
  return {done: !!(r && getComputedStyle(r).display!=='none'),
          cat: document.getElementById('rCat').textContent,
          reason: document.getElementById('rReason').textContent,
          time: document.getElementById('rTime').textContent,
          chips: [...document.querySelectorAll('#rChips .chip')].map(x=>x.textContent),
          err: (e && getComputedStyle(e).display!=='none') ? e.textContent : null};
})()"""


def wait_result(ws, tries=50):
    for _ in range(tries):
        st = ws.eval(RESULT_JS)
        if st and (st.get("done") or st.get("err")):
            return st
        time.sleep(1)
    return {"timeout": True}


def run_upload(ws):
    img = SAMPLES / "corridor_clutter_high_boxes.jpg"
    doc = ws.send("DOM.getDocument", {"depth": 1})
    root = doc["result"]["root"]["nodeId"]
    node = ws.send("DOM.querySelector", {"nodeId": root, "selector": "#fileInput"})["result"]["nodeId"]
    ws.send("DOM.setFileInputFiles", {"files": [str(img)], "nodeId": node})
    ws.eval("document.getElementById('fileInput').dispatchEvent(new Event('change'))")
    st = wait_result(ws)
    st["path"] = "upload"
    return st


def run_camera(ws):
    ws.eval("document.getElementById('btnCam').click()")
    time.sleep(4)
    cam = ws.eval("""(()=>{const v=document.getElementById('video');
        return {hasStream:!!(v&&v.srcObject), w:v?v.videoWidth:0, h:v?v.videoHeight:0,
                btn:document.getElementById('btnCam').textContent};})()""")
    ws.eval("document.getElementById('btnShot').click()")
    time.sleep(2)
    preview = ws.eval("""(()=>{const p=document.getElementById('preview');
        return {hasSrc:!!(p&&p.src&&p.src.startsWith('data:image/jpeg')), len:p&&p.src?p.src.length:0};})()""")
    st = wait_result(ws)
    st["path"] = "camera"
    st["camera"] = cam
    st["preview"] = preview
    return st


def main():
    if not Path(CHROME).exists():
        print("未找到 Chrome:", CHROME); sys.exit(2)
    report = {}
    proc = launch(["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    try:
        ws = attach()
        ws.send("Page.enable"); ws.send("DOM.enable"); ws.send("Runtime.enable")
        for _ in range(40):
            if ws.eval("document.readyState === 'complete' && !!document.getElementById('fileInput')"):
                break
            time.sleep(0.5)
        report["upload"] = run_upload(ws)
        report["overflow"] = ws.eval(
            "(()=>{const vw=document.documentElement.clientWidth;"
            "return {scrollW:document.documentElement.scrollWidth, clientW:vw,"
            "overflow:document.documentElement.scrollWidth>vw+1};})()")
        shot = ws.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        OUT_PNG.write_bytes(base64.b64decode(shot["result"]["data"]))
        report["camera"] = run_camera(ws)
        report["history_count"] = ws.eval(
            "(JSON.parse(localStorage.getItem('corridor_history_v1')||'[]')).length")
    finally:
        proc.terminate()

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # 控制台可能是 GBK，输出用 ASCII 转义避免 UnicodeEncodeError
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print("saved:", OUT_JSON, "|", OUT_PNG)


if __name__ == "__main__":
    main()
