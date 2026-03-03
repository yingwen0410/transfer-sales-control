"""
handlers.py
所有 API 路由處理邏輯。
BaseHandler 提供共用工具；每個資源群組獨立一個 Handler class。
server.py 的 dispatch() 負責依 method + path 呼叫對應 handler。
"""

import json
import os
import uuid
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from storage import load_data, save_data, transaction
from validation import (
    ValidationError,
    sanitize_record_create, sanitize_record_update,
    sanitize_part, sanitize_customer, sanitize_params,
    validate_record, validate_part, validate_customer,
)
from schema import (
    RECORD_READONLY, RECORD_BUSINESS_KEYS,
    PARAM_KEYS, PARAM_DEFAULTS,
)

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


# ── 共用工具 ─────────────────────────────────────────────────────────────────

class BaseHandler:
    def __init__(self, request_handler):
        """request_handler 是 BaseHTTPRequestHandler 實例，用來送回應。"""
        self.rh = request_handler

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        rh   = self.rh
        rh.send_response(status)
        rh.send_header("Content-Type",    "application/json; charset=utf-8")
        rh.send_header("Content-Length",  str(len(body)))
        rh.send_header("X-Content-Type-Options", "nosniff")
        rh.end_headers()
        rh.wfile.write(body)

    def send_file(self, filepath: str, content_type: str):
        with open(filepath, "rb") as f:
            body = f.read()
        rh = self.rh
        rh.send_response(200)
        rh.send_header("Content-Type",   content_type)
        rh.send_header("Content-Length", str(len(body)))
        rh.send_header("X-Content-Type-Options", "nosniff")
        rh.send_header("X-Frame-Options",        "SAMEORIGIN")
        rh.end_headers()
        rh.wfile.write(body)

    def read_body(self) -> dict:
        try:
            length = int(self.rh.headers.get("Content-Length", 0))
            if length <= 0 or length > 2_000_000:
                return {}
            raw = self.rh.rfile.read(length).decode("utf-8")
            return json.loads(raw)
        except Exception:
            return {}

    def error(self, msg: str, status: int = 400):
        self.send_json({"error": msg}, status)

    def ok(self, payload: dict = None, status: int = 200):
        self.send_json({"success": True, **(payload or {})}, status)


# ── 靜態檔案 ─────────────────────────────────────────────────────────────────

class StaticHandler(BaseHandler):
    def get(self):
        if os.path.exists(HTML_PATH):
            self.send_file(HTML_PATH, "text/html; charset=utf-8")
        else:
            self.error("index.html 不存在", 404)


# ── /api/records ─────────────────────────────────────────────────────────────

class RecordsHandler(BaseHandler):

    def get_list(self, query_string: str):
        qs      = parse_qs(query_string)
        q       = qs.get("q",      [""])[0].strip()[:200]
        status  = qs.get("status", [""])[0].strip()[:50]
        data    = load_data()
        records = data.get("records", [])

        if q:
            ql = q.lower()
            records = [r for r in records if
                ql in r.get("customer_name",     "").lower() or
                ql in r.get("customer_order_no", "").lower() or
                ql in r.get("xin_part_no",       "").lower() or
                ql in r.get("remark",            "").lower()]
        if status:
            records = [r for r in records if r.get("pad_status") == status]

        self.send_json({
            "records": records,
            "total":   len(records),
            "params":  data.get("params", {}),
        })

    def get_one(self, rec_id: str):
        data = load_data()
        rec  = next((r for r in data["records"] if r["id"] == rec_id), None)
        if rec:
            self.send_json(rec)
        else:
            self.error("找不到此筆資料", 404)

    def post(self):
        body = self.read_body()
        try:
            clean = sanitize_record_create(body)
            validate_record(clean, is_create=True)
        except ValidationError as e:
            self.error(e.message, e.status)
            return

        with transaction() as data:
            seq    = len(data["records"]) + 1
            record = {
                "id":                str(uuid.uuid4()),
                "seq":               seq,
                "txn_id":            f"TXN-{datetime.now().strftime('%Y%m')}-{seq:03d}",
                "pad_status":        "待建單",
                "pad_executed_at":   "",
                "pad_error":         "",
                "created_at":        datetime.now().strftime("%Y/%m/%d %H:%M"),
                # 業務欄位（已清理）
                **clean,
                # 旗標初始值
                "flag_xin_order":    "",
                "flag_xin_sale":     "",
                "flag_ju_purchase":  "",
                "flag_ju_receipt":   "",
                "flag_ju_sale":      "待人工",
            }
            data["records"].append(record)

        self.ok({"record": record}, status=201)

    def put(self, rec_id: str):
        body = self.read_body()
        try:
            clean = sanitize_record_update(body)
            validate_record(clean, is_create=False)
        except ValidationError as e:
            self.error(e.message, e.status)
            return

        with transaction() as data:
            idx = next(
                (i for i, r in enumerate(data["records"]) if r["id"] == rec_id),
                None
            )
            if idx is None:
                # transaction 的 yield 後不會 save（因為要拋例外終止 contextmanager）
                # 改用手動 raise 讓 transaction 不寫入
                raise _AbortTransaction()

            original = data["records"][idx]
            updated  = {**original}

            # 只合併白名單內且有傳入的欄位
            for k, v in clean.items():
                if k not in RECORD_READONLY:
                    updated[k] = v

            # 保護唯讀系統欄位
            for k in RECORD_READONLY:
                updated[k] = original[k]

            # 若原已完成，且有業務欄位變動 → 降回待建單（已修改）
            if original.get("pad_status") == "已完成":
                if any(k in clean for k in RECORD_BUSINESS_KEYS):
                    updated["pad_status"]       = "待建單（已修改）"
                    updated["flag_xin_order"]   = ""
                    updated["flag_xin_sale"]    = ""
                    updated["flag_ju_purchase"] = ""
                    updated["flag_ju_receipt"]  = ""
                    updated["flag_ju_sale"]     = "待人工"

            updated["modified_at"]    = datetime.now().strftime("%Y/%m/%d %H:%M")
            data["records"][idx]      = updated

        self.ok({"record": updated})

    def delete(self, rec_id: str):
        with transaction() as data:
            before = len(data["records"])
            data["records"] = [r for r in data["records"] if r["id"] != rec_id]
            if len(data["records"]) == before:
                raise _AbortTransaction(not_found=True)
            for i, r in enumerate(data["records"]):
                r["seq"] = i + 1

        self.ok()


# ── /api/parts ───────────────────────────────────────────────────────────────

class PartsHandler(BaseHandler):

    def get_list(self, query_string: str):
        qs   = parse_qs(query_string)
        q    = qs.get("q", [""])[0].strip()[:200].lower()
        data = load_data()
        parts = data.get("parts", [])
        if q:
            parts = [p for p in parts if
                q in p.get("xin_no", "").lower() or
                q in p.get("name",   "").lower() or
                q in p.get("ju_no",  "").lower()]
        self.send_json({"parts": parts})

    def get_one(self, part_id: str):
        data = load_data()
        part = next((p for p in data["parts"] if p["id"] == part_id), None)
        if part:
            self.send_json(part)
        else:
            self.error("找不到品號", 404)

    def post(self):
        body = self.read_body()
        clean = sanitize_part(body)
        try:
            validate_part(clean, is_create=True)
        except ValidationError as e:
            self.error(e.message, e.status)
            return

        with transaction() as data:
            if any(p["xin_no"] == clean["xin_no"] for p in data["parts"]):
                raise _AbortTransaction(conflict=True,
                                        msg=f"品號「{clean['xin_no']}」已存在")
            part = {"id": str(uuid.uuid4()), **clean}
            data["parts"].append(part)

        self.ok({"part": part}, status=201)

    def put(self, part_id: str):
        body  = self.read_body()
        clean = sanitize_part(body)
        try:
            validate_part(clean, is_create=False)
        except ValidationError as e:
            self.error(e.message, e.status)
            return

        with transaction() as data:
            idx = next((i for i, p in enumerate(data["parts"]) if p["id"] == part_id), None)
            if idx is None:
                raise _AbortTransaction(not_found=True)
            xin_no = clean.get("xin_no", data["parts"][idx]["xin_no"])
            if any(p["xin_no"] == xin_no and p["id"] != part_id for p in data["parts"]):
                raise _AbortTransaction(conflict=True,
                                        msg=f"品號「{xin_no}」已存在")
            data["parts"][idx].update(clean)
            part = data["parts"][idx]

        self.ok({"part": part})

    def delete(self, part_id: str):
        with transaction() as data:
            before = len(data["parts"])
            data["parts"] = [p for p in data["parts"] if p["id"] != part_id]
            if len(data["parts"]) == before:
                raise _AbortTransaction(not_found=True)
        self.ok()


# ── /api/customers ───────────────────────────────────────────────────────────

class CustomersHandler(BaseHandler):

    def get_list(self, query_string: str):
        qs   = parse_qs(query_string)
        q    = qs.get("q", [""])[0].strip()[:200].lower()
        data = load_data()
        customers = data.get("customers", [])
        if q:
            customers = [c for c in customers if
                q in c.get("name", "").lower() or
                q in c.get("code", "").lower()]
        self.send_json({"customers": customers})

    def get_one(self, cust_id: str):
        data = load_data()
        cust = next((c for c in data["customers"] if c["id"] == cust_id), None)
        if cust:
            self.send_json(cust)
        else:
            self.error("找不到客戶", 404)

    def post(self):
        body  = self.read_body()
        clean = sanitize_customer(body)
        try:
            validate_customer(clean, is_create=True)
        except ValidationError as e:
            self.error(e.message, e.status)
            return

        with transaction() as data:
            if any(c["name"] == clean["name"] for c in data["customers"]):
                raise _AbortTransaction(conflict=True,
                                        msg=f"客戶「{clean['name']}」已存在")
            cust = {"id": str(uuid.uuid4()), **clean}
            data["customers"].append(cust)

        self.ok({"customer": cust}, status=201)

    def put(self, cust_id: str):
        body  = self.read_body()
        clean = sanitize_customer(body)
        try:
            validate_customer(clean, is_create=False)
        except ValidationError as e:
            self.error(e.message, e.status)
            return

        with transaction() as data:
            idx = next((i for i, c in enumerate(data["customers"]) if c["id"] == cust_id), None)
            if idx is None:
                raise _AbortTransaction(not_found=True)
            name = clean.get("name", data["customers"][idx]["name"])
            if any(c["name"] == name and c["id"] != cust_id for c in data["customers"]):
                raise _AbortTransaction(conflict=True,
                                        msg=f"客戶「{name}」已存在")
            data["customers"][idx].update(clean)
            cust = data["customers"][idx]

        self.ok({"customer": cust})

    def delete(self, cust_id: str):
        with transaction() as data:
            before = len(data["customers"])
            data["customers"] = [c for c in data["customers"] if c["id"] != cust_id]
            if len(data["customers"]) == before:
                raise _AbortTransaction(not_found=True)
        self.ok()


# ── /api/params ──────────────────────────────────────────────────────────────

class ParamsHandler(BaseHandler):

    def get(self):
        data = load_data()
        self.send_json(data.get("params", {}))

    def post(self):
        body  = self.read_body()
        clean = sanitize_params(body)

        with transaction() as data:
            data["params"].update(clean)
            data["params"]["updated_at"] = datetime.now().strftime("%Y/%m/%d")
            params = data["params"]

        self.ok({"params": params})




# ── /api/pad/* ── Power Automate 專用 endpoint ───────────────────────────────
#
# 這兩個 endpoint 與 /api/records 的一般 PUT 刻意分開，原因：
#   1. 欄位白名單完全不同：PA 只能寫 pad_* 欄位，不能動業務欄位
#   2. 驗證規則不同：pad_status 只允許特定值，不需 batch_total 驗證
#   3. 讓 PA flow 的 URL 語意更清晰，日後除錯容易定位

_PAD_ALLOWED_STATUSES = {"待建單", "建單中", "已完成", "錯誤", "待建單（已修改）"}


class PadHandler(BaseHandler):
    """
    /api/pad/queue  GET  → 取得 PA 待處理清單
    /api/pad/{id}   POST → PA 回寫執行結果
    """

    def get_queue(self, query_string: str):
        """
        回傳 pad_status 符合條件的記錄。
        Query params:
            status  篩選 pad_status（預設 "待建單"，可逗號分隔多個值）
            limit   最多回傳幾筆（預設 50，最大 200）
        回應：
            { "records": [...], "total": N, "fetched_at": "..." }
        """
        qs = parse_qs(query_string)
        raw_status = qs.get("status", ["待建單"])[0].strip()
        statuses   = {s.strip() for s in raw_status.split(",") if s.strip()}
        statuses   = statuses & _PAD_ALLOWED_STATUSES
        if not statuses:
            statuses = {"待建單"}

        limit = min(int(qs.get("limit", ["50"])[0] or 50), 200)

        data    = load_data()
        records = [r for r in data.get("records", [])
                   if r.get("pad_status") in statuses]
        records.sort(key=lambda r: r.get("seq", 0))
        records = records[:limit]

        self.send_json({
            "records":    records,
            "total":      len(records),
            "fetched_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        })

    def post_result(self, rec_id: str):
        """
        PA 建完單後回寫執行結果。
        Body（JSON）：
            pad_status      必填  "建單中" | "已完成" | "錯誤"
            pad_executed_at 選填  留空由後端自動填入
            pad_error       選填  錯誤訊息（pad_status=="錯誤" 時必填）
        回應：
            { "success": true, "record": { ...更新後完整記錄... } }
        """
        body = self.read_body()

        pad_status = str(body.get("pad_status", "")).strip()[:50]
        pad_error  = str(body.get("pad_error",  "")).strip()[:500]
        pad_exec   = str(body.get("pad_executed_at", "")).strip()[:30]

        if pad_status not in _PAD_ALLOWED_STATUSES:
            self.error(
                f"pad_status 不合法，允許值：{', '.join(sorted(_PAD_ALLOWED_STATUSES))}",
                400
            )
            return

        if pad_status == "錯誤" and not pad_error:
            self.error("pad_status 為「錯誤」時，pad_error 不能為空", 400)
            return

        if not pad_exec:
            pad_exec = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        with transaction() as data:
            idx = next(
                (i for i, r in enumerate(data["records"]) if r["id"] == rec_id),
                None
            )
            if idx is None:
                raise _AbortTransaction(not_found=True)

            r = data["records"][idx]

            # 只允許覆蓋 pad_* 欄位，任何業務欄位都不動
            r["pad_status"]      = pad_status
            r["pad_executed_at"] = pad_exec
            r["pad_error"]       = pad_error

            # 若 PA 宣告「已完成」，自動把四張 ERP 旗標標為完成
            # flag_ju_sale 維持人工確認，不自動設定
            if pad_status == "已完成":
                r["flag_xin_order"]   = r.get("flag_xin_order")   or "是"
                r["flag_xin_sale"]    = r.get("flag_xin_sale")    or "是"
                r["flag_ju_purchase"] = r.get("flag_ju_purchase") or "是"
                r["flag_ju_receipt"]  = r.get("flag_ju_receipt")  or "是"

            updated = data["records"][idx]

        self.ok({"record": updated})

# ── _AbortTransaction：讓 transaction() contextmanager 不寫入 ────────────────

class _AbortTransaction(Exception):
    """
    在 `with transaction() as data:` 區塊內拋出，
    可讓 transaction() 不執行 _write_json，並由外層 dispatch 轉成 HTTP 回應。
    """
    def __init__(self, not_found=False, conflict=False, msg=""):
        self.not_found = not_found
        self.conflict  = conflict
        self.msg       = msg


# ── 主路由分發 ────────────────────────────────────────────────────────────────

def dispatch(request_handler):
    """
    根據 HTTP method + path 呼叫對應 handler。
    request_handler 是 BaseHTTPRequestHandler 實例。
    """
    parsed = urlparse(request_handler.path)
    method = request_handler.command
    path   = parsed.path.rstrip("/") or "/"
    qs     = parsed.query

    def _handle():
        # 靜態首頁
        if method == "GET" and path in ("/", "/index.html"):
            StaticHandler(request_handler).get()
            return

        # ── /api/records ──
        if path == "/api/records":
            h = RecordsHandler(request_handler)
            if   method == "GET":  h.get_list(qs)
            elif method == "POST": h.post()
            else: _method_not_allowed(request_handler)
            return

        if path.startswith("/api/records/"):
            rec_id = path.split("/")[-1]
            h = RecordsHandler(request_handler)
            if   method == "GET":    h.get_one(rec_id)
            elif method == "PUT":    h.put(rec_id)
            elif method == "DELETE": h.delete(rec_id)
            else: _method_not_allowed(request_handler)
            return

        # ── /api/parts ──
        if path == "/api/parts":
            h = PartsHandler(request_handler)
            if   method == "GET":  h.get_list(qs)
            elif method == "POST": h.post()
            else: _method_not_allowed(request_handler)
            return

        if path.startswith("/api/parts/"):
            part_id = path.split("/")[-1]
            h = PartsHandler(request_handler)
            if   method == "GET":    h.get_one(part_id)
            elif method == "PUT":    h.put(part_id)
            elif method == "DELETE": h.delete(part_id)
            else: _method_not_allowed(request_handler)
            return

        # ── /api/customers ──
        if path == "/api/customers":
            h = CustomersHandler(request_handler)
            if   method == "GET":  h.get_list(qs)
            elif method == "POST": h.post()
            else: _method_not_allowed(request_handler)
            return

        if path.startswith("/api/customers/"):
            cust_id = path.split("/")[-1]
            h = CustomersHandler(request_handler)
            if   method == "GET":    h.get_one(cust_id)
            elif method == "PUT":    h.put(cust_id)
            elif method == "DELETE": h.delete(cust_id)
            else: _method_not_allowed(request_handler)
            return

        # ── /api/params ──
        if path == "/api/params":
            h = ParamsHandler(request_handler)
            if   method == "GET":  h.get()
            elif method == "POST": h.post()
            else: _method_not_allowed(request_handler)
            return


        # ── /api/pad ── Power Automate 專用 ──
        if path == "/api/pad/queue":
            h = PadHandler(request_handler)
            if method == "GET": h.get_queue(qs)
            else: _method_not_allowed(request_handler)
            return

        if path.startswith("/api/pad/") and path != "/api/pad/queue":
            rec_id = path.split("/")[-1]
            h = PadHandler(request_handler)
            if method == "POST": h.post_result(rec_id)
            else: _method_not_allowed(request_handler)
            return

        # 404
        BaseHandler(request_handler).error("找不到路徑", 404)

    # 統一例外處理
    try:
        _handle()
    except _AbortTransaction as e:
        h = BaseHandler(request_handler)
        if e.not_found:
            h.error("找不到此筆資料", 404)
        elif e.conflict:
            h.error(e.msg or "資料重複", 409)
        else:
            h.error("操作取消", 400)
    except RuntimeError as e:
        BaseHandler(request_handler).error(str(e), 500)
    except Exception as e:
        print(f"[ERROR] {e}")
        BaseHandler(request_handler).error("伺服器內部錯誤", 500)


def _method_not_allowed(request_handler):
    BaseHandler(request_handler).error("不支援此 HTTP 方法", 405)
