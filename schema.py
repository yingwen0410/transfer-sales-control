"""
schema.py
定義所有資料表的欄位白名單、類型、預設值。
任何寫入操作都必須透過這裡過濾，不允許直接 **body 合併。
"""

# ── records 表 ────────────────────────────────────────────────────────────────

# 新增時允許由前端傳入的欄位（系統欄位由後端自動產生）
RECORD_WRITABLE_CREATE = {
    # 欄位名稱        : (型別, 預設值, 最大長度)
    "customer_name"    : ("str",   "",          200),
    "customer_code"    : ("str",   "",          100),
    "customer_order_no": ("str",   "",          200),
    "remark"           : ("str",   "",          500),
    "xin_part_no"      : ("str",   "",          200),
    "ju_part_no"       : ("str",   "",          200),
    "part_name"        : ("str",   "",          200),
    "qty"              : ("int",   0,           None),
    "sale_price"       : ("float", 0.0,         None),
    "transfer_ratio"   : ("float", 0.0,         None),
    "transfer_price"   : ("float", 0.0,         None),
    "delivery_date"    : ("str",   "",          20),
    "ship_date"        : ("str",   "",          20),
    "month_first_day"  : ("str",   "",          20),
    "cross_month"      : ("str",   "否",        10),
    "invoice_date"     : ("str",   "",          20),
    "invoice_no"       : ("str",   "",          50),
    "invoice_type"     : ("str",   "電子發票",  20),
    "batches"          : ("list",  [],          None),
    "batch_total"      : ("int",   0,           None),
}

# 修改時允許更新的欄位（包含旗標欄位）
RECORD_WRITABLE_UPDATE = {
    **RECORD_WRITABLE_CREATE,
    "flag_xin_order"   : ("str",   "",    10),
    "flag_xin_sale"    : ("str",   "",    10),
    "flag_ju_purchase" : ("str",   "",    10),
    "flag_ju_receipt"  : ("str",   "",    10),
    "flag_ju_sale"     : ("str",   "",    10),
    "pad_status"       : ("str",   "",    50),
    "pad_executed_at"  : ("str",   "",    30),
    "pad_error"        : ("str",   "",   500),
}

# 修改時，若這些業務欄位有變動，且原 pad_status == 已完成，則自動降回「待建單（已修改）」
RECORD_BUSINESS_KEYS = {
    "customer_name", "customer_code", "customer_order_no", "remark",
    "xin_part_no", "ju_part_no", "part_name",
    "qty", "sale_price", "transfer_ratio", "transfer_price",
    "delivery_date", "ship_date", "month_first_day",
    "cross_month", "invoice_date", "invoice_no", "invoice_type",
    "batches", "batch_total",
}

# 系統唯讀欄位，任何 PUT 都不能覆蓋
RECORD_READONLY = {"id", "seq", "txn_id", "created_at"}

# ── parts 表 ──────────────────────────────────────────────────────────────────
PART_WRITABLE = {
    "xin_no": ("str", "",  200),
    "ju_no":  ("str", "",  200),
    "name":   ("str", "",  200),
    "spec":   ("str", "",  200),
}

# ── customers 表 ─────────────────────────────────────────────────────────────
CUSTOMER_WRITABLE = {
    "name": ("str", "", 200),
    "code": ("str", "", 100),
    "note": ("str", "", 500),
}

# ── params 允許的 key ────────────────────────────────────────────────────────
PARAM_KEYS = {
    "transfer_ratio",
    "xin_order_type", "xin_sale_type",
    "ju_pur_type", "ju_rec_type", "ju_sale_type",
    "xin_to_ju_code", "ju_to_xin_code",
}

PARAM_DEFAULTS = {
    "transfer_ratio" : 0.22,
    "xin_order_type" : "221A",
    "xin_sale_type"  : "231A",
    "ju_pur_type"    : "331A",
    "ju_rec_type"    : "341A",
    "ju_sale_type"   : "2312",
    "xin_to_ju_code" : "T99001",
    "ju_to_xin_code" : "B0306",
}
