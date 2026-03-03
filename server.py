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
DEFAULT_DATA = {
    "records": [],
    "parts": [],
    "customers": [],
    "params": {
        "transfer_ratio": 0.22,
        "xin_order_type": "221A",
        "xin_sale_type":  "231A",
        "ju_pur_type":    "331A",
        "ju_rec_type":    "341A",
        "ju_sale_type":   "2312",
        "xin_to_ju_code": "T99001",
        "ju_to_xin_code": "B0306",
        "updated_at":     datetime.now().strftime("%Y/%m/%d"),
    }
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # 向前相容：舊資料沒有 parts/customers 欄位
    raw.setdefault("parts",     [])
    raw.setdefault("customers", [])
    raw.setdefault("params",    DEFAULT_DATA["params"])
    return raw

def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    shutil.move(tmp, DATA_FILE)

# ── 輸入清理（防止不可信內容存入 JSON）──────────────────────────────────────
def str_field(body, key, default="", maxlen=500):
    val = body.get(key, default)
    if not isinstance(val, str):
        val = str(val) if val is not None else default
    return val.strip()[:maxlen]

def int_field(body, key, default=0):
    try:
        return int(body.get(key, default))
    except (TypeError, ValueError):
        return default

def float_field(body, key, default=0.0):
    try:
        return float(body.get(key, default))
    except (TypeError, ValueError):
        return default

def list_field(body, key):
    val = body.get(key, [])
    return val if isinstance(val, list) else []

# ── HTTP 請求處理 ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        if args and str(args[1]) not in ("200", "204", "201"):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5000")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, filepath, content_type):
        with open(filepath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 1_000_000:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw)
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5000")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET ───────────────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path

        # 靜態首頁
        if path in ("/", "/index.html"):
            html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
            if os.path.exists(html_path):
                self.send_file(html_path, "text/html; charset=utf-8")
            else:
                self.send_json({"error": "index.html 不存在"}, 404)
            return

        # 所有記錄
        if path == "/api/records":
            qs     = parse_qs(parsed.query)
            data   = load_data()
            records = data.get("records", [])
            q      = qs.get("q",      [""])[0].strip()[:200]
            status = qs.get("status", [""])[0].strip()[:50]
            if q:
                ql = q.lower()
                records = [r for r in records if
                    ql in r.get("customer_name",     "").lower() or
                    ql in r.get("customer_order_no", "").lower() or
                    ql in r.get("xin_part_no",       "").lower() or
                    ql in r.get("remark",            "").lower()]
            if status:
                records = [r for r in records if r.get("pad_status") == status]
            self.send_json({"records": records, "total": len(records),
                            "params": data.get("params", {})})
            return

        # 單筆記錄
        if path.startswith("/api/records/"):
            rec_id = path.split("/")[-1]
            data   = load_data()
            rec    = next((r for r in data["records"] if r["id"] == rec_id), None)
            self.send_json(rec if rec else {"error": "找不到此筆資料"},
                           200 if rec else 404)
            return

        # 參數
        if path == "/api/params":
            data = load_data()
            self.send_json(data.get("params", {}))
            return

        # ── 品號對照表 ────────────────────────────────────────────────────────
        if path == "/api/parts":
            qs   = parse_qs(parsed.query)
            data = load_data()
            parts = data.get("parts", [])
            q    = qs.get("q", [""])[0].strip()[:200].lower()
            if q:
                parts = [p for p in parts if
                    q in p.get("xin_no", "").lower() or
                    q in p.get("name",   "").lower() or
                    q in p.get("ju_no",  "").lower()]
            self.send_json({"parts": parts})
            return

        if path.startswith("/api/parts/"):
            part_id = path.split("/")[-1]
            data    = load_data()
            part    = next((p for p in data["parts"] if p["id"] == part_id), None)
            self.send_json(part if part else {"error": "找不到品號"}, 200 if part else 404)
            return

        # ── 客戶清單 ──────────────────────────────────────────────────────────
        if path == "/api/customers":
            qs   = parse_qs(parsed.query)
            data = load_data()
            customers = data.get("customers", [])
            q    = qs.get("q", [""])[0].strip()[:200].lower()
            if q:
                customers = [c for c in customers if
                    q in c.get("name", "").lower() or
                    q in c.get("code", "").lower()]
            self.send_json({"customers": customers})
            return

        if path.startswith("/api/customers/"):
            cust_id = path.split("/")[-1]
            data    = load_data()
            cust    = next((c for c in data["customers"] if c["id"] == cust_id), None)
            self.send_json(cust if cust else {"error": "找不到客戶"}, 200 if cust else 404)
            return

        self.send_json({"error": "找不到路徑"}, 404)

    # ── POST ──────────────────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path
        body = self.read_body()

        # 新增記錄
        if path == "/api/records":
            data     = load_data()
            existing = data.get("records", [])
            seq      = len(existing) + 1

            # 清理批號列表
            raw_batches = list_field(body, "batches")
            batches = []
            for b in raw_batches[:4]:
                if isinstance(b, dict):
                    no  = str(b.get("no",  "")).strip()[:100]
                    qty = int(b.get("qty", 0)) if str(b.get("qty", 0)).isdigit() else 0
                    if no:
                        batches.append({"no": no, "qty": qty})

            record = {
                "id":                str(uuid.uuid4()),
                "seq":               seq,
                "txn_id":            f"TXN-{datetime.now().strftime('%Y%m')}-{seq:03d}",
                "pad_status":        "待建單",
                "pad_executed_at":   "",
                "pad_error":         "",
                "created_at":        datetime.now().strftime("%Y/%m/%d %H:%M"),
                "customer_name":     str_field(body, "customer_name"),
                "customer_code":     str_field(body, "customer_code"),
                "customer_order_no": str_field(body, "customer_order_no"),
                "remark":            str_field(body, "remark"),
                "xin_part_no":       str_field(body, "xin_part_no"),
                "ju_part_no":        str_field(body, "ju_part_no"),
                "part_name":         str_field(body, "part_name"),
                "qty":               int_field(body,   "qty"),
                "sale_price":        float_field(body, "sale_price"),
                "transfer_ratio":    float_field(body, "transfer_ratio"),
                "transfer_price":    float_field(body, "transfer_price"),
                "delivery_date":     str_field(body, "delivery_date"),
                "ship_date":         str_field(body, "ship_date"),
                "month_first_day":   str_field(body, "month_first_day"),
                "cross_month":       str_field(body, "cross_month") or "否",
                "invoice_date":      str_field(body, "invoice_date"),
                "invoice_no":        str_field(body, "invoice_no"),
                "invoice_type":      str_field(body, "invoice_type") or "電子發票",
                "batches":           batches,
                "batch_total":       int_field(body, "batch_total"),
                "flag_xin_order":    "",
                "flag_xin_sale":     "",
                "flag_ju_purchase":  "",
                "flag_ju_receipt":   "",
                "flag_ju_sale":      "待人工",
            }
            data["records"].append(record)
            save_data(data)
            self.send_json({"success": True, "record": record}, 201)
            return

        # 更新參數
        if path == "/api/params":
            data   = load_data()
            params = data.get("params", {})
            allowed_keys = {
                "transfer_ratio", "xin_order_type", "xin_sale_type",
                "ju_pur_type", "ju_rec_type", "ju_sale_type",
                "xin_to_ju_code", "ju_to_xin_code"
            }
            for k in allowed_keys:
                if k in body:
                    if k == "transfer_ratio":
                        try:
                            params[k] = float(body[k])
                        except (TypeError, ValueError):
                            pass
                    else:
                        params[k] = str(body[k]).strip()[:50]
            params["updated_at"] = datetime.now().strftime("%Y/%m/%d")
            data["params"] = params
            save_data(data)
            self.send_json({"success": True, "params": params})
            return

        # 新增品號
        if path == "/api/parts":
            xin_no = str_field(body, "xin_no")
            if not xin_no:
                self.send_json({"error": "欣家豐品號為必填"}, 400)
                return
            data = load_data()
            # 不允許重複品號
            if any(p["xin_no"] == xin_no for p in data["parts"]):
                self.send_json({"error": f"品號「{xin_no}」已存在"}, 409)
                return
            part = {
                "id":     str(uuid.uuid4()),
                "xin_no": xin_no,
                "ju_no":  str_field(body, "ju_no"),
                "name":   str_field(body, "name"),
                "spec":   str_field(body, "spec"),
            }
            data["parts"].append(part)
            save_data(data)
            self.send_json({"success": True, "part": part}, 201)
            return

        # 新增客戶
        if path == "/api/customers":
            name = str_field(body, "name")
            if not name:
                self.send_json({"error": "客戶名稱為必填"}, 400)
                return
            data = load_data()
            if any(c["name"] == name for c in data["customers"]):
                self.send_json({"error": f"客戶「{name}」已存在"}, 409)
                return
            cust = {
                "id":   str(uuid.uuid4()),
                "name": name,
                "code": str_field(body, "code"),
                "note": str_field(body, "note"),
            }
            data["customers"].append(cust)
            save_data(data)
            self.send_json({"success": True, "customer": cust}, 201)
            return

        self.send_json({"error": "找不到路徑"}, 404)

    # ── PUT ───────────────────────────────────────────────────────────────────
    def do_PUT(self):
        path = urlparse(self.path).path
        body = self.read_body()

        # 修改記錄
        if path.startswith("/api/records/"):
            rec_id = path.split("/")[-1]
            data   = load_data()
            idx    = next((i for i, r in enumerate(data["records"]) if r["id"] == rec_id), None)
            if idx is None:
                self.send_json({"error": "找不到此筆資料"}, 404)
                return

            original = data["records"][idx]

            # 允許 PUT 更新的欄位白名單
            updatable = {
                "customer_name", "customer_code", "customer_order_no", "remark",
                "xin_part_no", "ju_part_no", "part_name",
                "qty", "sale_price", "transfer_ratio", "transfer_price",
                "delivery_date", "ship_date", "month_first_day",
                "cross_month", "invoice_date", "invoice_no", "invoice_type",
                "batches", "batch_total",
                "flag_xin_order", "flag_xin_sale",
                "flag_ju_purchase", "flag_ju_receipt", "flag_ju_sale",
                "pad_status", "pad_executed_at", "pad_error",
            }
            updated = dict(original)
            for k in updatable:
                if k not in body:
                    continue
                if k in ("qty", "batch_total"):
                    updated[k] = int_field(body, k)
                elif k in ("sale_price", "transfer_ratio", "transfer_price"):
                    updated[k] = float_field(body, k)
                elif k == "batches":
                    raw_b = list_field(body, "batches")
                    clean = []
                    for b in raw_b[:4]:
                        if isinstance(b, dict):
                            no  = str(b.get("no", "")).strip()[:100]
                            qty_b = int(b.get("qty", 0)) if str(b.get("qty", 0)).lstrip('-').isdigit() else 0
                            if no:
                                clean.append({"no": no, "qty": qty_b})
                    updated[k] = clean
                else:
                    updated[k] = str_field(body, k)

            # 保護唯讀欄位
            updated["id"]         = original["id"]
            updated["seq"]        = original["seq"]
            updated["txn_id"]     = original["txn_id"]
            updated["created_at"] = original["created_at"]

            # 若原已完成，修改業務欄位後自動降回「待建單（已修改）」
            business_keys = {
                "customer_name", "customer_code", "customer_order_no", "remark",
                "xin_part_no", "ju_part_no", "part_name",
                "qty", "sale_price", "transfer_ratio", "transfer_price",
                "delivery_date", "ship_date", "month_first_day",
                "cross_month", "invoice_date", "invoice_no", "invoice_type",
                "batches", "batch_total",
            }
            if original.get("pad_status") == "已完成" and any(k in body for k in business_keys):
                updated["pad_status"]       = "待建單（已修改）"
                updated["flag_xin_order"]   = ""
                updated["flag_xin_sale"]    = ""
                updated["flag_ju_purchase"] = ""
                updated["flag_ju_receipt"]  = ""
                updated["flag_ju_sale"]     = "待人工"

            updated["modified_at"] = datetime.now().strftime("%Y/%m/%d %H:%M")
            data["records"][idx]   = updated
            save_data(data)
            self.send_json({"success": True, "record": updated})
            return

        # 修改品號
        if path.startswith("/api/parts/"):
            part_id = path.split("/")[-1]
            data    = load_data()
            idx     = next((i for i, p in enumerate(data["parts"]) if p["id"] == part_id), None)
            if idx is None:
                self.send_json({"error": "找不到品號"}, 404)
                return
            xin_no = str_field(body, "xin_no")
            if not xin_no:
                self.send_json({"error": "欣家豐品號不能為空"}, 400)
                return
            # 重複檢查（排除自身）
            if any(p["xin_no"] == xin_no and p["id"] != part_id for p in data["parts"]):
                self.send_json({"error": f"品號「{xin_no}」已存在"}, 409)
                return
            data["parts"][idx].update({
                "xin_no": xin_no,
                "ju_no":  str_field(body, "ju_no"),
                "name":   str_field(body, "name"),
                "spec":   str_field(body, "spec"),
            })
            save_data(data)
            self.send_json({"success": True, "part": data["parts"][idx]})
            return

        # 修改客戶
        if path.startswith("/api/customers/"):
            cust_id = path.split("/")[-1]
            data    = load_data()
            idx     = next((i for i, c in enumerate(data["customers"]) if c["id"] == cust_id), None)
            if idx is None:
                self.send_json({"error": "找不到客戶"}, 404)
                return
            name = str_field(body, "name")
            if not name:
                self.send_json({"error": "客戶名稱不能為空"}, 400)
                return
            if any(c["name"] == name and c["id"] != cust_id for c in data["customers"]):
                self.send_json({"error": f"客戶「{name}」已存在"}, 409)
                return
            data["customers"][idx].update({
                "name": name,
                "code": str_field(body, "code"),
                "note": str_field(body, "note"),
            })
            save_data(data)
            self.send_json({"success": True, "customer": data["customers"][idx]})
            return

        self.send_json({"error": "找不到路徑"}, 404)

    # ── DELETE ────────────────────────────────────────────────────────────────
    def do_DELETE(self):
        path = urlparse(self.path).path

        if path.startswith("/api/records/"):
            rec_id = path.split("/")[-1]
            data   = load_data()
            before = len(data["records"])
            data["records"] = [r for r in data["records"] if r["id"] != rec_id]
            if len(data["records"]) == before:
                self.send_json({"error": "找不到此筆資料"}, 404)
                return
            for i, r in enumerate(data["records"]):
                r["seq"] = i + 1
            save_data(data)
            self.send_json({"success": True})
            return

        if path.startswith("/api/parts/"):
            part_id = path.split("/")[-1]
            data    = load_data()
            before  = len(data["parts"])
            data["parts"] = [p for p in data["parts"] if p["id"] != part_id]
            if len(data["parts"]) == before:
                self.send_json({"error": "找不到品號"}, 404)
                return
            save_data(data)
            self.send_json({"success": True})
            return

        if path.startswith("/api/customers/"):
            cust_id = path.split("/")[-1]
            data    = load_data()
            before  = len(data["customers"])
            data["customers"] = [c for c in data["customers"] if c["id"] != cust_id]
            if len(data["customers"]) == before:
                self.send_json({"error": "找不到客戶"}, 404)
                return
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
