"""打印局域网访问地址，方便手机扫码/输入。

用法: python -m app.show_ip
"""

from __future__ import annotations

import os
import socket

from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", "8000"))


def lan_ip() -> str:
    """拿本机对外网卡 IP。连 UDP 不会真的发包，只是让系统选路由。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def main() -> None:
    ip = lan_ip()
    print("=" * 52)
    print("  电脑本机访问 :", f"http://127.0.0.1:{PORT}")
    print("  手机访问     :", f"http://{ip}:{PORT}")
    print("=" * 52)
    print("  手机需与电脑连同一个 Wi-Fi。若打不开，先放行防火墙 8000 端口。")
    try:
        import qrcode  # 可选依赖

        qr = qrcode.QRCode(border=1)
        qr.add_data(f"http://{ip}:{PORT}")
        qr.make()
        qr.print_ascii(invert=True)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
