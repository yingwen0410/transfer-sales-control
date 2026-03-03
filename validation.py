"""
validation.py
所有輸入清理（sanitize）與業務規則驗證（validate）。
清理：將不可信的原始輸入轉為乾淨的 Python 值。
驗證：對清理後的值檢查業務規則，回傳錯誤清單。
"""

from schema import (
    RECORD_WRITABLE_CREATE, RECORD_WRITABLE_UPDATE,
    PART_WRITABLE, CUSTOMER_WRITABLE, PARAM_KEYS,
)


# ── 通用清理工具 ──────────────────────────────────────────────────────────────

def _clean_str(val, default="", maxlen=500):
    if val is None:
        return default
    s = str(val).strip()
    return s[:maxlen]

def _clean_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default

def _clean_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def _clean_list(val):
    return val if isinstance(val, list) else []


def _clean_by_schema(body: dict, schema: dict) -> dict:
    """
    依照 schema 定義逐欄清理 body，只回傳 schema 中有定義的欄位。
    schema 格式：{ "欄位名": ("型別", 預設值, 最大長度或None) }
    """
    result = {}
    for key, (typ, default, maxlen) in schema.items():
        if key not in body:
            continue  # 不在 body 裡的欄位不寫入（PATCH 語意）
        raw = body[key]
        if typ == "str":
            result[key] = _clean_str(raw, default, maxlen or 500)
        elif typ == "int":
            result[key] = _clean_int(raw, default)
        elif typ == "float":
            result[key] = _clean_float(raw, default)
        elif typ == "list":
            result[key] = _clean_list(raw)
        else:
            result[key] = raw
    return result


# ── 批號清理 ──────────────────────────────────────────────────────────────────

def clean_batches(raw_list) -> list:
    """清理批號列表，最多 4 批，每批 no 不能為空。"""
    result = []
    if not isinstance(raw_list, list):
        return result
    for item in raw_list[:4]:
        if not isinstance(item, dict):
            continue
        no  = _clean_str(item.get("no",  ""), maxlen=100)
        qty = _clean_int(item.get("qty", 0))
        if no:  # no 為空則跳過
            result.append({"no": no, "qty": max(0, qty)})
    return result


# ── records 清理 ──────────────────────────────────────────────────────────────

def sanitize_record_create(body: dict) -> dict:
    data = _clean_by_schema(body, RECORD_WRITABLE_CREATE)
    if "batches" in body:
        data["batches"] = clean_batches(body.get("batches", []))
    return data

def sanitize_record_update(body: dict) -> dict:
    data = _clean_by_schema(body, RECORD_WRITABLE_UPDATE)
    if "batches" in body:
        data["batches"] = clean_batches(body.get("batches", []))
    return data


# ── parts / customers / params 清理 ──────────────────────────────────────────

def sanitize_part(body: dict) -> dict:
    return _clean_by_schema(body, PART_WRITABLE)

def sanitize_customer(body: dict) -> dict:
    return _clean_by_schema(body, CUSTOMER_WRITABLE)

def sanitize_params(body: dict) -> dict:
    result = {}
    for k in PARAM_KEYS:
        if k not in body:
            continue
        if k == "transfer_ratio":
            result[k] = _clean_float(body[k], 0.0)
        else:
            result[k] = _clean_str(body[k], maxlen=50)
    return result


# ── 業務規則驗證 ──────────────────────────────────────────────────────────────

class ValidationError(Exception):
    """驗證失敗，message 為人類可讀的錯誤說明。"""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status  = status


def validate_record(data: dict, is_create: bool = True):
    """
    驗證 record 資料的業務規則。
    is_create=True  → 必填欄位檢查 + batch_total 驗證
    is_create=False → 只驗證有傳入的欄位（PATCH 語意），但若有 batches 就一定驗 batch_total
    raises ValidationError on failure.
    """
    errors = []

    if is_create:
        # 必填欄位
        required = {
            "customer_name":      "客戶名稱",
            "customer_order_no":  "客戶單號",
            "xin_part_no":        "欣家豐品號",
            "invoice_no":         "發票號碼",
            "delivery_date":      "預交日",
            "ship_date":          "出貨日",
        }
        for field, label in required.items():
            if not data.get(field, ""):
                errors.append(f"{label} 為必填")

        qty = data.get("qty", 0)
        if qty <= 0:
            errors.append("訂單數量必須大於 0")

        sale_price = data.get("sale_price", 0.0)
        if sale_price <= 0:
            errors.append("對外單價必須大於 0")

    # batch_total 驗證（新增必驗；修改時若有傳 batches 或 batch_total 就驗）
    has_batches_update = "batches" in data or "batch_total" in data
    if is_create or has_batches_update:
        batches    = data.get("batches", [])
        batch_total = data.get("batch_total", 0)
        computed   = sum(b.get("qty", 0) for b in batches)

        if is_create:
            qty = data.get("qty", 0)
            # 批號合計必須 == 訂單數量
            if computed == 0:
                errors.append("至少需填寫一筆批號")
            elif computed != qty:
                errors.append(
                    f"批號數量合計（{computed}）≠ 訂單數量（{qty}），差 {computed - qty:+d}"
                )
        # 前端計算的 batch_total 必須與後端重算一致（防止竄改）
        if batch_total != computed:
            errors.append(
                f"batch_total（{batch_total}）與批號實際合計（{computed}）不符"
            )

    if errors:
        raise ValidationError("；".join(errors), status=400)


def validate_part(data: dict, is_create: bool = True):
    if is_create or "xin_no" in data:
        if not data.get("xin_no", ""):
            raise ValidationError("欣家豐品號為必填", 400)

def validate_customer(data: dict, is_create: bool = True):
    if is_create or "name" in data:
        if not data.get("name", ""):
            raise ValidationError("客戶名稱為必填", 400)
