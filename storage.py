"""
storage.py
負責 data.json 的讀取、寫入，以及跨平台的檔案鎖定。

鎖定策略：
  - Windows : msvcrt.locking（byte-range locking）
  - Linux/macOS : fcntl.flock（advisory lock）

所有寫入都透過 atomic_write()：先寫 .tmp，確認成功後再 rename 覆蓋，
防止寫入中途斷電造成 JSON 損毀。
"""

import json
import os
import sys
import shutil
import threading
from datetime import datetime
from contextlib import contextmanager

# ── 資料檔路徑 ────────────────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

# ── 執行緒鎖（同一 process 內的並發寫入保護）────────────────────────────────
_thread_lock = threading.Lock()

# ── 跨平台檔案鎖（process 間保護，例如 PAD 同時寫入）────────────────────────
if sys.platform == "win32":
    import msvcrt

    @contextmanager
    def _file_lock(fp):
        """Windows: 對前 1 byte 做 locking，阻塞直到取得鎖。"""
        fp.seek(0)
        while True:
            try:
                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                import time
                time.sleep(0.05)
        try:
            yield
        finally:
            fp.seek(0)
            msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    @contextmanager
    def _file_lock(fp):
        """Linux/macOS: exclusive advisory lock，阻塞直到取得。"""
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


# ── 預設資料結構 ──────────────────────────────────────────────────────────────
def _default_data() -> dict:
    return {
        "records":   [],
        "parts":     [],
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


# ── 向前相容：舊 JSON 缺少新欄位時補上預設值 ─────────────────────────────────
def _migrate(data: dict) -> dict:
    defaults = _default_data()
    for key in ("records", "parts", "customers", "params"):
        data.setdefault(key, defaults[key])
    # params 裡的新 key 也補上
    for k, v in defaults["params"].items():
        data["params"].setdefault(k, v)
    return data


# ── 公開 API ──────────────────────────────────────────────────────────────────

def load_data() -> dict:
    """讀取並回傳完整資料。若檔案不存在則建立預設值。"""
    if not os.path.exists(DATA_FILE):
        data = _default_data()
        _write_json(data)
        return data

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"data.json 格式損毀，請還原備份：{e}") from e

    return _migrate(data)


def save_data(data: dict) -> None:
    """
    以執行緒鎖 + 檔案鎖雙重保護寫入，使用 atomic rename 防止半寫損毀。
    """
    with _thread_lock:
        _write_json(data)


def _write_json(data: dict) -> None:
    """內部：atomic write（tmp → rename）+ 檔案鎖。"""
    tmp_path = DATA_FILE + ".tmp"
    # 建立或開啟 lock 檔（與資料檔同目錄）
    lock_path = DATA_FILE + ".lock"

    with open(lock_path, "a", encoding="utf-8") as lock_fp:
        with _file_lock(lock_fp):
            # 寫入暫存檔
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # atomic rename（Windows 上 shutil.move 會先刪目標再 rename）
            shutil.move(tmp_path, DATA_FILE)


# ── 便捷的 read-modify-write helper ─────────────────────────────────────────
@contextmanager
def transaction():
    """
    用法：
        with transaction() as data:
            data["records"].append(new_record)
        # 離開 with 區塊時自動 save_data(data)

    若 with 區塊內拋出任何例外（包括 _AbortTransaction），
    不執行寫入，例外繼續往上傳遞。
    """
    with _thread_lock:
        data = load_data()
        try:
            yield data
        except BaseException:
            # 任何例外都不寫入，直接往上拋
            raise
        else:
            # 只有正常離開 with 區塊才寫入
            _write_json(data)
