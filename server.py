#!/usr/bin/env python3
"""
server.py
移轉銷貨主控系統 — 後端伺服器入口
職責：啟動 HTTPServer、OPTIONS 預檢、將所有請求轉給 handlers.dispatch()

用法：python server.py
預設埠號：5000
"""

import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from storage import DATA_FILE
from handlers import dispatch
from auth import init_pad_token

PORT = 5000


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        """只記錄非 2xx 的請求，減少終端雜訊。"""
        if args and str(args[1])[:1] not in ("2",):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def do_OPTIONS(self):
        """CORS 預檢（僅允許同源）。"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",  "http://localhost:5000")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):    dispatch(self)
    def do_POST(self):   dispatch(self)
    def do_PUT(self):    dispatch(self)
    def do_DELETE(self): dispatch(self)


if __name__ == "__main__":
    print("=" * 55)
    print("  移轉銷貨主控系統 — 後端伺服器")
    print("=" * 55)
    print(f"  資料檔案：{DATA_FILE}")
    print(f"  伺服器位址：http://localhost:{PORT}")
    print(f"  啟動時間：{datetime.now().strftime('%Y/%m/%d %H:%M:%S')}")
    print("=" * 55)
    print("  員工請用瀏覽器開啟：http://[伺服器IP]:5000")
    print("  按 Ctrl+C 停止伺服器")
    print("=" * 55)

    # 初始化 PAD token（若未設環境變數則自動產生並印出）
    init_pad_token()

    # 確保預設 admin 帳號存在
    from storage import load_data, save_data
    from auth import ensure_default_admin
    d = load_data()
    ensure_default_admin(d)
    save_data(d)

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n伺服器已停止。")
        sys.exit(0)
