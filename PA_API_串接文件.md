# Power Automate 串接文件
## 移轉銷貨主控系統 — PAD 專用 API

> 版本：v2.1　更新：2025/06
> 伺服器位址範例：`http://192.168.1.xx:5000`（依實際部署 IP 調整）

---

## 一、PA Flow 建議流程

```
[排程觸發（每 N 分鐘）]
        │
        ▼
GET /api/pad/queue?status=待建單
        │
        ├─ total == 0 → 結束本次執行
        │
        └─ total > 0
               │
               ▼
        對每筆 record 執行：
               │
               ├─ 1. POST /api/pad/{id}   body: { pad_status: "建單中" }
               │
               ├─ 2. 在 ERP 建立欣豐訂單、欣豐銷貨、鉅侖採購、鉅侖進貨
               │
               ├─ 成功 → POST /api/pad/{id}  body: { pad_status: "已完成" }
               │
               └─ 失敗 → POST /api/pad/{id}  body: { pad_status: "錯誤",
                                                      pad_error: "錯誤原因" }
```

---

## 二、API 清單

### 2-1　GET `/api/pad/queue` — 取得待處理清單

**用途：** PA 每次執行時先呼叫此 endpoint，取得需要建單的記錄清單。

**Query 參數：**

| 參數 | 必填 | 說明 | 範例 |
|------|------|------|------|
| `status` | 否 | 篩選 pad_status，預設 `待建單`。可逗號分隔多個值 | `待建單` 或 `待建單,待建單（已修改）` |
| `limit` | 否 | 最多回傳筆數，預設 50，最大 200 | `50` |

**完整 URL 範例：**
```
GET http://192.168.1.xx:5000/api/pad/queue?status=待建單&limit=50
GET http://192.168.1.xx:5000/api/pad/queue?status=待建單,待建單（已修改）
```

**成功回應（HTTP 200）：**
```json
{
  "records": [
    {
      "id":                "550e8400-e29b-41d4-a716-446655440000",
      "seq":               1,
      "txn_id":            "TXN-202401-001",
      "pad_status":        "待建單",
      "pad_executed_at":   "",
      "pad_error":         "",
      "customer_name":     "測試客戶有限公司",
      "customer_code":     "C001",
      "customer_order_no": "IIP02-2402000015",
      "remark":            "測試客戶有限公司 IIP02-2402000015",
      "xin_part_no":       "A-001",
      "ju_part_no":        "J-001",
      "part_name":         "零件名稱",
      "qty":               100,
      "sale_price":        500.0,
      "transfer_ratio":    0.22,
      "transfer_price":    110,
      "delivery_date":     "2024-03-15",
      "ship_date":         "2024-03-10",
      "month_first_day":   "2024/03/01",
      "cross_month":       "否",
      "invoice_date":      "2024-03-10",
      "invoice_no":        "AB12345678",
      "invoice_type":      "電子發票",
      "batches": [
        { "no": "LOT-001", "qty": 60 },
        { "no": "LOT-002", "qty": 40 }
      ],
      "batch_total":       100,
      "flag_xin_order":    "",
      "flag_xin_sale":     "",
      "flag_ju_purchase":  "",
      "flag_ju_receipt":   "",
      "flag_ju_sale":      "待人工",
      "created_at":        "2024/03/01 09:30"
    }
  ],
  "total":      1,
  "fetched_at": "2024/03/01 09:31:00"
}
```

**PA 常用欄位對照：**

| 欄位 | PA 變數路徑 | 用途 |
|------|------------|------|
| `id` | `body/records/0/id` | 回寫時的 URL 參數 |
| `txn_id` | `body/records/0/txn_id` | ERP 建單備註用 |
| `customer_code` | `body/records/0/customer_code` | 鉅侖客戶代號 |
| `xin_part_no` | `body/records/0/xin_part_no` | 欣家豐品號 |
| `ju_part_no` | `body/records/0/ju_part_no` | 鉅侖品號 |
| `qty` | `body/records/0/qty` | 訂單數量 |
| `transfer_price` | `body/records/0/transfer_price` | 移轉單價（整數，已計算好） |
| `invoice_no` | `body/records/0/invoice_no` | 發票號碼 |
| `ship_date` | `body/records/0/ship_date` | 出貨日期（`YYYY-MM-DD`） |
| `month_first_day` | `body/records/0/month_first_day` | 當月第一天（`YYYY/MM/DD`） |
| `remark` | `body/records/0/remark` | 單據備註（已組合好） |
| `batches` | `body/records/0/batches` | 批號陣列（含 no, qty） |
| `cross_month` | `body/records/0/cross_month` | 是否跨月開票（`是`/`否`） |

---

### 2-2　POST `/api/pad/{id}` — 回寫執行結果

**用途：** PA 每個建單步驟完成後（或失敗時）呼叫，更新系統狀態。

**URL：**
```
POST http://192.168.1.xx:5000/api/pad/{record的id}
```

**Headers：**
```
Content-Type: application/json
```

**Request Body：**

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `pad_status` | string | ✅ | 見下表允許值 |
| `pad_executed_at` | string | 否 | 執行時間，留空由後端自動填入 |
| `pad_error` | string | 條件必填 | `pad_status=="錯誤"` 時必填，其他傳空字串 |

**`pad_status` 允許值：**

| 值 | 時機 |
|----|------|
| `建單中` | PA 開始建單時，先呼叫一次（避免重複執行） |
| `已完成` | 四張 ERP 單據全部建立成功後 |
| `錯誤` | 任一步驟失敗，需同時傳入 `pad_error` 說明原因 |

**範例 1：開始建單（標記為建單中）**
```json
POST /api/pad/550e8400-e29b-41d4-a716-446655440000

{
  "pad_status": "建單中",
  "pad_error":  ""
}
```

**範例 2：建單成功**
```json
{
  "pad_status":      "已完成",
  "pad_executed_at": "2024/03/01 09:35:22",
  "pad_error":       ""
}
```

**範例 3：建單失敗**
```json
{
  "pad_status": "錯誤",
  "pad_error":  "鉅侖採購單建立失敗：客戶代號 C001 不存在於 ERP"
}
```

**成功回應（HTTP 200）：**
```json
{
  "success": true,
  "record": {
    "id":              "550e8400-e29b-41d4-a716-446655440000",
    "pad_status":      "已完成",
    "pad_executed_at": "2024/03/01 09:35:22",
    "pad_error":       "",
    "flag_xin_order":  "是",
    "flag_xin_sale":   "是",
    "flag_ju_purchase":"是",
    "flag_ju_receipt": "是",
    "flag_ju_sale":    "待人工"
  }
}
```

> ⚠️ `flag_ju_sale`（鉅侖銷貨）**不會被自動設定**，需人工在網頁介面確認。

**錯誤回應：**

| HTTP 狀態 | `error` 內容 | 原因 |
|-----------|--------------|------|
| 400 | `pad_status 不合法，允許值：...` | 傳入非法 pad_status |
| 400 | `pad_status 為「錯誤」時，pad_error 不能為空` | 缺少錯誤說明 |
| 404 | `找不到此筆資料` | record id 不存在 |
| 500 | `伺服器內部錯誤` | 伺服器端例外，查看 server log |

---

## 三、PA 設定步驟（HTTP 動作）

### 步驟 1：取得待建單清單

在 PA 中新增「HTTP」動作：

```
方法:   GET
URI:    http://192.168.1.xx:5000/api/pad/queue?status=待建單
標頭:   （不需要）
```

剖析 JSON 回應，Schema 設定為：
```json
{
  "type": "object",
  "properties": {
    "records": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id":                { "type": "string" },
          "txn_id":            { "type": "string" },
          "customer_code":     { "type": "string" },
          "customer_order_no": { "type": "string" },
          "xin_part_no":       { "type": "string" },
          "ju_part_no":        { "type": "string" },
          "qty":               { "type": "integer" },
          "transfer_price":    { "type": "integer" },
          "sale_price":        { "type": "number" },
          "invoice_no":        { "type": "string" },
          "ship_date":         { "type": "string" },
          "month_first_day":   { "type": "string" },
          "remark":            { "type": "string" },
          "cross_month":       { "type": "string" },
          "batches": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "no":  { "type": "string" },
                "qty": { "type": "integer" }
              }
            }
          }
        }
      }
    },
    "total": { "type": "integer" }
  }
}
```

### 步驟 2：條件判斷

新增「條件」：`total` **等於** `0` → 終止（不需建單）

### 步驟 3：Apply to each（對每筆記錄）

對 `records` 陣列套用「Apply to each」：

**3a. 標記建單中（防止重複執行）**
```
方法:    POST
URI:     http://192.168.1.xx:5000/api/pad/@{items('Apply_to_each')?['id']}
標頭:    Content-Type: application/json
本文:    { "pad_status": "建單中", "pad_error": "" }
```

**3b. 在 ERP 建立四張單（依貴公司 ERP API 操作）**

**3c. 全部成功 → 回寫已完成**
```
方法:    POST
URI:     http://192.168.1.xx:5000/api/pad/@{items('Apply_to_each')?['id']}
標頭:    Content-Type: application/json
本文:    {
           "pad_status": "已完成",
           "pad_error":  ""
         }
```

**3d. 任一失敗 → 回寫錯誤（在 Try/Catch 或 Configure run after 中）**
```json
{
  "pad_status": "錯誤",
  "pad_error":  "欣豐訂單建立失敗：@{outputs('建立欣豐訂單')?['body/error']}"
}
```

---

## 四、注意事項

1. **建單中先標記再執行**：避免伺服器重啟或 PA 重跑時重複建單。
2. **`flag_ju_sale` 不會自動完成**：鉅侖銷貨需人工在網頁確認，這是刻意設計。
3. **重試邏輯**：若 HTTP 動作回傳 5xx，建議設定「重試原則」為「固定間隔，3次，60秒」。
4. **CORS 限制**：伺服器只允許 `http://localhost:5000` 的 Origin，PA 的 HTTP 動作不帶 Origin header，因此可以正常呼叫（不受 CORS 限制）。
5. **批號陣列讀取**：`batches` 是 JSON 陣列，在 PA 中需再用「Apply to each」展開，取 `no` 和 `qty`。
6. **日期格式**：`ship_date` 格式為 `YYYY-MM-DD`（ISO 8601），`month_first_day` 格式為 `YYYY/MM/DD`。
