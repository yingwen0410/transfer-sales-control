"""
auth.py
身份驗證、Session Token 管理、操作日誌（audit log）。

設計原則：
  - 密碼以 SHA-256 + salt 儲存，不明文
  - Token 為 32 bytes 隨機值，存在記憶體中（重啟後失效，需重新登入）
  - Token 透過 Authorization: Bearer <token> header 傳遞
  - 日誌存於 data.json 的 audit_logs 陣列，網頁可查看
  - 最多保留最新 2000 筆日誌，自動輪替
  - PAD 專用路由（/api/pad/*）使用獨立 PAD_TOKEN，不需帳號登入
"""

import hashlib
import hmac
import os
import secrets
import threading
from datetime import datetime

# ── 常數 ─────────────────────────────────────────────────────────────────────
MAX_AUDIT_LOGS   = 2000   # 日誌最大保留筆數
TOKEN_BYTES      = 32     # session token 長度
SALT_BYTES       = 16     # 密碼 salt 長度
MIN_PW_LEN       = 6      # 最短密碼長度

# PAD 專用 token（從環境變數讀，若未設定則啟動時產生並印出）
_PAD_TOKEN: str = os.environ.get("PAD_TOKEN", "")

# ── 記憶體 Session 表 ─────────────────────────────────────────────────────────
# { token_str: {"username": str, "login_at": str} }
_sessions: dict = {}
_sessions_lock  = threading.Lock()


# ── 初始化（由 storage.load_data 呼叫後執行）────────────────────────────────

def init_pad_token() -> str:
    """
    取得或產生 PAD token。
    若環境變數 PAD_TOKEN 有設定就用它，否則每次啟動自動產生並印出。
    """
    global _PAD_TOKEN
    if not _PAD_TOKEN:
        _PAD_TOKEN = secrets.token_hex(TOKEN_BYTES)
        print("=" * 55)
        print("  PAD Token（請設定在 PAD flow 的 Header）：")
        print(f"  X-PAD-Token: {_PAD_TOKEN}")
        print("=" * 55)
    return _PAD_TOKEN


def get_pad_token() -> str:
    return _PAD_TOKEN


# ── 密碼工具 ──────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """回傳 hex(salt) + ":" + hex(sha256(salt + password))"""
    salt   = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.sha256(salt + password.encode("utf-8")).hexdigest()
    return salt.hex() + ":" + digest

def verify_password(password: str, stored: str) -> bool:
    """驗證密碼，使用 hmac.compare_digest 防 timing attack。"""
    try:
        salt_hex, digest = stored.split(":", 1)
        salt   = bytes.fromhex(salt_hex)
        expect = hashlib.sha256(salt + password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expect, digest)
    except Exception:
        return False


# ── 帳號管理（操作 data["users"]）─────────────────────────────────────────────

def get_users(data: dict) -> list:
    return data.setdefault("users", [])

def find_user(data: dict, username: str) -> dict | None:
    return next((u for u in get_users(data) if u["username"] == username), None)

def create_user(data: dict, username: str, password: str, role: str = "user") -> dict:
    """
    新增使用者。
    role: "admin"（可管理帳號）或 "user"（一般操作）
    """
    username = username.strip()[:50]
    if not username:
        raise ValueError("使用者名稱不能為空")
    if len(password) < MIN_PW_LEN:
        raise ValueError(f"密碼至少需 {MIN_PW_LEN} 個字元")
    if find_user(data, username):
        raise ValueError(f"使用者「{username}」已存在")
    if role not in ("admin", "user"):
        role = "user"

    user = {
        "username":   username,
        "password":   hash_password(password),
        "role":       role,
        "created_at": datetime.now().strftime("%Y/%m/%d %H:%M"),
        "disabled":   False,
    }
    get_users(data).append(user)
    return user

def delete_user(data: dict, username: str, operator: str) -> None:
    """刪除使用者，不能刪除自己。"""
    if username == operator:
        raise ValueError("不能刪除自己的帳號")
    users = get_users(data)
    before = len(users)
    data["users"] = [u for u in users if u["username"] != username]
    if len(data["users"]) == before:
        raise ValueError(f"找不到使用者「{username}」")
    # 同時踢出該使用者的 session
    revoke_user_sessions(username)

def change_password(data: dict, username: str, new_password: str) -> None:
    if len(new_password) < MIN_PW_LEN:
        raise ValueError(f"密碼至少需 {MIN_PW_LEN} 個字元")
    user = find_user(data, username)
    if not user:
        raise ValueError(f"找不到使用者「{username}」")
    user["password"] = hash_password(new_password)

def ensure_default_admin(data: dict) -> None:
    """
    若 users 為空，自動建立預設 admin 帳號。
    預設帳密：admin / admin123
    首次登入後請立即修改密碼。
    """
    if not get_users(data):
        create_user(data, "admin", "admin123", role="admin")
        print("[AUTH] 已建立預設管理員帳號：admin / admin123，請登入後立即修改密碼")


# ── Session 管理 ──────────────────────────────────────────────────────────────

def create_session(username: str) -> str:
    """建立新 session，回傳 token string。"""
    token = secrets.token_hex(TOKEN_BYTES)
    with _sessions_lock:
        _sessions[token] = {
            "username": username,
            "login_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }
    return token

def validate_token(token: str) -> dict | None:
    """
    驗證 token，回傳 session dict 或 None。
    """
    if not token:
        return None
    with _sessions_lock:
        return _sessions.get(token)

def revoke_token(token: str) -> None:
    with _sessions_lock:
        _sessions.pop(token, None)

def revoke_user_sessions(username: str) -> None:
    """踢出某使用者的所有 session（刪帳號或停用時用）。"""
    with _sessions_lock:
        to_remove = [t for t, s in _sessions.items() if s["username"] == username]
        for t in to_remove:
            del _sessions[t]


# ── Token 取得工具（從 HTTP header 解析）────────────────────────────────────

def extract_token(request_handler) -> str:
    """從 Authorization: Bearer <token> header 取出 token。"""
    auth = request_handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""

def extract_pad_token(request_handler) -> str:
    """從 X-PAD-Token header 取出 PAD token。"""
    return request_handler.headers.get("X-PAD-Token", "").strip()


# ── 路由鑑權工具 ──────────────────────────────────────────────────────────────

# 完全公開的路徑（不需任何驗證）
PUBLIC_PATHS = {"/", "/index.html", "/api/login"}

# PAD 專用路徑（用 X-PAD-Token 驗證，不需使用者帳號）
PAD_PATHS_PREFIX = "/api/pad/"

def require_auth(request_handler, path: str) -> dict | None:
    """
    檢查請求是否有合法身份。

    回傳值：
        dict  → {"username": str, "role": str, "is_pad": bool}，代表驗證通過
        None  → 驗證失敗，此函數已送出 401 回應，呼叫端直接 return 即可

    PAD 路由用 X-PAD-Token，一般路由用 Bearer token。
    """
    from handlers import BaseHandler
    h = BaseHandler(request_handler)

    # 公開路徑直接放行
    if path in PUBLIC_PATHS:
        return {"username": "anonymous", "role": "guest", "is_pad": False}

    # PAD 專用路徑：檢查 X-PAD-Token
    if path.startswith(PAD_PATHS_PREFIX):
        pad_tok = extract_pad_token(request_handler)
        if pad_tok and hmac.compare_digest(pad_tok, _PAD_TOKEN):
            return {"username": "PAD", "role": "pad", "is_pad": True}
        h.send_json({"error": "PAD Token 無效，請在 Header 加入 X-PAD-Token"}, 401)
        return None

    # 一般路徑：檢查 Bearer token
    token   = extract_token(request_handler)
    session = validate_token(token)
    if not session:
        h.send_json({"error": "未登入或 Session 已過期，請重新登入"}, 401)
        return None

    # 取得 role（從 data 讀，這裡只從 session 帶基本資訊）
    return {"username": session["username"], "role": session.get("role", "user"), "is_pad": False}


# ── 操作日誌 ─────────────────────────────────────────────────────────────────

def write_audit(data: dict, operator: str, action: str,
                resource: str, resource_id: str = "",
                before: dict = None, after: dict = None,
                note: str = "") -> None:
    """
    寫入操作日誌到 data["audit_logs"]。
    before/after 為修改前後的完整物件（或部分欄位），用於 diff。
    超過 MAX_AUDIT_LOGS 時自動刪除最舊的。
    """
    logs = data.setdefault("audit_logs", [])

    # 計算 diff（只記錄有變動的欄位）
    diff = {}
    if before and after:
        all_keys = set(before) | set(after)
        for k in all_keys:
            bv = before.get(k)
            av = after.get(k)
            if bv != av:
                diff[k] = {"before": bv, "after": av}

    entry = {
        "timestamp":   datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "operator":    operator,
        "action":      action,        # CREATE / UPDATE / DELETE / LOGIN / LOGOUT
        "resource":    resource,      # records / parts / customers / params / users
        "resource_id": resource_id,
        "diff":        diff,
        "note":        note[:200],
    }
    logs.append(entry)

    # 超過上限時，保留最新的
    if len(logs) > MAX_AUDIT_LOGS:
        data["audit_logs"] = logs[-MAX_AUDIT_LOGS:]
