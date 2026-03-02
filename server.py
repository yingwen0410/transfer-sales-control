#!/usr/bin/env python3
"""
移轉銷貨主控系統 - 後端伺服器
用法：python server.py
預設埠號：5000
資料檔案：data.json（與 server.py 同目錄）
"""

import json
import os
import sys
import uuid
import shutil
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
PORT = 5000

# ── 資料初始化 ────────────────────────────────────────────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        save_data({"records": [], "params": {
            "transfer_ratio": 0.22,
            "updated_at": datetime.now().strftime("%Y/%m/%d")
        }})
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    # 寫入前先備份（防止寫入中途斷電造成資料毀損）
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    shutil.move(tmp, DATA_FILE)

# ── HTTP 請求處理 ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # 只顯示錯誤，減少終端機雜訊
        if args and str(args[1]) not in ("200", "204"):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, filepath, content_type):
        with open(filepath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 靜態檔案
        if path == "/" or path == "/index.html":
            html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
            if os.path.exists(html_path):
                self.send_file(html_path, "text/html; charset=utf-8")
            else:
                self.send_json({"error": "index.html 不存在"}, 404)
            return

        # API：取得所有記錄
        if path == "/api/records":
            qs = parse_qs(parsed.query)
            data = load_data()
            records = data.get("records", [])

            # 查詢篩選
            q = qs.get("q", [""])[0].strip()
            status = qs.get("status", [""])[0].strip()
            if q:
                q_lower = q.lower()
                records = [r for r in records if
                    q_lower in r.get("customer_name", "").lower() or
                    q_lower in r.get("customer_order_no", "").lower() or
                    q_lower in r.get("xin_part_no", "").lower() or
                    q_lower in r.get("remark", "").lower()]
            if status:
                records = [r for r in records if r.get("pad_status") == status]

            self.send_json({"records": records, "total": len(records),
                           "params": data.get("params", {})})
            return

        # API：取得單筆記錄
        if path.startswith("/api/records/"):
            rec_id = path.split("/")[-1]
            data = load_data()
            rec = next((r for r in data["records"] if r["id"] == rec_id), None)
            if rec:
                self.send_json(rec)
            else:
                self.send_json({"error": "找不到此筆資料"}, 404)
            return

        # API：取得參數設定
        if path == "/api/params":
            data = load_data()
            self.send_json(data.get("params", {}))
            return

        self.send_json({"error": "找不到路徑"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path

        # 新增記錄
        if path == "/api/records":
            body = self.read_body()
            data = load_data()

            # 產生唯一 ID 與流水號
            existing = data.get("records", [])
            seq = len(existing) + 1
            now = datetime.now().strftime("%Y%m%d-%H%M%S")

            record = {
                "id":               str(uuid.uuid4()),
                "seq":              seq,
                "txn_id":           f"TXN-{datetime.now().strftime('%Y%m')}-{seq:03d}",
                "pad_status":       "待建單",
                "pad_executed_at":  "",
                "pad_error":        "",
                "created_at":       datetime.now().strftime("%Y/%m/%d %H:%M"),
                # Zone A
                "customer_name":    body.get("customer_name", ""),
                "customer_code":    body.get("customer_code", ""),
                "customer_order_no":body.get("customer_order_no", ""),
                "remark":           body.get("remark", ""),
                "xin_part_no":      body.get("xin_part_no", ""),
                "ju_part_no":       body.get("ju_part_no", ""),
                "part_name":        body.get("part_name", ""),
                "qty":              body.get("qty", 0),
                "sale_price":       body.get("sale_price", 0),
                "transfer_ratio":   body.get("transfer_ratio", 0),
                "transfer_price":   body.get("transfer_price", 0),
                "delivery_date":    body.get("delivery_date", ""),
                "ship_date":        body.get("ship_date", ""),
                "month_first_day":  body.get("month_first_day", ""),
                "cross_month":      body.get("cross_month", "否"),
                "invoice_date":     body.get("invoice_date", ""),
                "invoice_no":       body.get("invoice_no", ""),
                "invoice_type":     body.get("invoice_type", "電子發票"),
                # Zone B 批號
                "batches":          body.get("batches", []),
                "batch_total":      body.get("batch_total", 0),
                # Zone E 旗標
                "flag_xin_order":   "",
                "flag_xin_sale":    "",
                "flag_ju_purchase": "",
                "flag_ju_receipt":  "",
                "flag_ju_sale":     "待人工",
            }
            data["records"].append(record)
            save_data(data)
            self.send_json({"success": True, "record": record}, 201)
            return

        # 更新參數設定
        if path == "/api/params":
            body = self.read_body()
            data = load_data()
            data["params"].update(body)
            data["params"]["updated_at"] = datetime.now().strftime("%Y/%m/%d")
            save_data(data)
            self.send_json({"success": True, "params": data["params"]})
            return

        self.send_json({"error": "找不到路徑"}, 404)

    def do_PUT(self):
        path = urlparse(self.path).path

        # 修改記錄
        if path.startswith("/api/records/"):
            rec_id = path.split("/")[-1]
            body = self.read_body()
            data = load_data()
            idx = next((i for i, r in enumerate(data["records"]) if r["id"] == rec_id), None)
            if idx is None:
                self.send_json({"error": "找不到此筆資料"}, 404)
                return

            # 保留系統欄位，更新其餘欄位
            original = data["records"][idx]
            updated = {**original, **body}
            updated["id"]         = original["id"]
            updated["seq"]        = original["seq"]
            updated["txn_id"]     = original["txn_id"]
            updated["created_at"] = original["created_at"]
            # 若原本已完成，修改後重設為待建單（已修改）
            if original.get("pad_status") == "已完成":
                updated["pad_status"] = "待建單（已修改）"
                updated["flag_xin_order"]   = ""
                updated["flag_xin_sale"]    = ""
                updated["flag_ju_purchase"] = ""
                updated["flag_ju_receipt"]  = ""
                updated["flag_ju_sale"]     = "待人工"
            updated["modified_at"] = datetime.now().strftime("%Y/%m/%d %H:%M")

            data["records"][idx] = updated
            save_data(data)
            self.send_json({"success": True, "record": updated})
            return

        self.send_json({"error": "找不到路徑"}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path

        if path.startswith("/api/records/"):
            rec_id = path.split("/")[-1]
            data = load_data()
            original_len = len(data["records"])
            data["records"] = [r for r in data["records"] if r["id"] != rec_id]
            if len(data["records"]) == original_len:
                self.send_json({"error": "找不到此筆資料"}, 404)
                return
            # 重新編號 seq
            for i, r in enumerate(data["records"]):
                r["seq"] = i + 1
            save_data(data)
            self.send_json({"success": True})
            return

        self.send_json({"error": "找不到路徑"}, 404)


# ── 啟動 ──────────────────────────────────────────────────────────────────────
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

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n伺服器已停止。")
        sys.exit(0)
