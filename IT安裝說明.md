# 移轉銷貨主控系統 — IT 安裝說明

## 系統需求
- Python 3.6 以上（Windows/Linux/macOS 均支援）
- 不需要安裝任何第三方套件，Python 內建即可

---

## 安裝步驟

### 步驟 1：確認 Python 版本
```
python --version
```
若顯示 3.6 以上即可。若未安裝，請至 https://www.python.org 下載。

### 步驟 2：複製檔案到伺服器
將以下三個檔案放到同一個資料夾（例如 \\server\移轉銷貨\）：
- server.py
- index.html
- （data.json 首次啟動時自動產生）

### 步驟 3：啟動伺服器
```
cd \\server\移轉銷貨
python server.py
```
看到以下畫面表示成功：
```
=======================================================
  移轉銷貨主控系統 — 後端伺服器
=======================================================
  資料檔案：...\data.json
  伺服器位址：http://localhost:5000
  啟動時間：2025/03/06 08:00:00
=======================================================
  員工請用瀏覽器開啟：http://[伺服器IP]:5000
  按 Ctrl+C 停止伺服器
=======================================================
```

### 步驟 4：告知員工網址
找出伺服器 IP（例如 192.168.1.100），通知員工用瀏覽器開啟：
```
http://192.168.1.100:5000
```

---

## 設定開機自動啟動（Windows）

1. 建立 `start_server.bat`，內容：
```bat
@echo off
cd /d \\server\移轉銷貨
python server.py
```

2. 將此 .bat 檔放入 Windows 工作排程器：
   - 開始 → 搜尋「工作排程器」
   - 建立基本工作 → 觸發條件選「電腦啟動時」
   - 動作選「啟動程式」，選擇 start_server.bat

---

## PAD 讀取 data.json

PAD 讀取的欄位對照（data.json 結構）：

```json
{
  "records": [
    {
      "pad_status":       "待建單",      ← PAD 篩選此欄位
      "remark":           "佳邦 IIP02-2402000015",
      "xin_part_no":      "CUA21A02001",
      "ju_part_no":       "CUA21A02001",
      "qty":              7,
      "transfer_price":   955,
      "delivery_date":    "2024-03-06",
      "ship_date":        "2024-03-06",
      "month_first_day":  "2024/03/01",
      "batches": [
        { "no": "231124-5150AN0", "qty": 3 },
        { "no": "231124-5150AN0（佳邦）", "qty": 4 }
      ],
      "flag_xin_order":   "",   ← PAD 完成後寫 "是"
      "flag_xin_sale":    "",
      "flag_ju_purchase": "",
      "flag_ju_receipt":  "",
      "flag_ju_sale":     "待人工"
    }
  ]
}
```

PAD 更新狀態的方式：直接修改 data.json 對應欄位，
或呼叫 API：PUT http://[伺服器IP]:5000/api/records/{id}

---

## 常見問題

**Q：員工開啟網頁顯示「無法連線」**
A：確認 server.py 是否仍在執行，防火牆是否允許 5000 port。

**Q：想更換 port 號**
A：修改 server.py 第 15 行 `PORT = 5000` 為想要的號碼。

**Q：data.json 備份**
A：server.py 每次寫入前會先產生 .tmp 暫存，再覆蓋正式檔。
建議每天排程備份 data.json 到另一個資料夾。
