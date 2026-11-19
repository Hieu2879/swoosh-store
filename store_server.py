import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import sqlite3
import sys
import threading
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from datetime import date, datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("SWOOSH_DB", ROOT / "data" / "swoosh.sqlite3"))
SESSION_SECONDS = 8 * 60 * 60
COOKIE_SECURE = os.environ.get("SWOOSH_COOKIE_SECURE") == "1"
TRUST_PROXY = os.environ.get("TRUST_PROXY", os.environ.get("SWOOSH_TRUST_PROXY", "0")) == "1"
SIZES = {38, 39, 40, 41, 42, 43, 44, 45}
INITIAL_PRODUCTS = [
    ("aj5", "Air Jordan 5", 210, 10, "#e5e0f0", [["#2b4a9a", "#111", "#fff"], ["#111", "#c4161c", "#eee"], ["#e8e8e8", "#222", "#777"]]),
    ("aj1", "Air Jordan 1 Low", 149, 10, "#f2e0eb", [["#d9d9d9", "#111", "#fff"], ["#f5f5f5", "#1b3a8a", "#fff"], ["#111", "#e03a2f", "#eee"]]),
    ("aj12", "Air Jordan 12 Retro", 189, 10, "#edf2d7", [["#f1f1f1", "#111", "#c9a227"]]),
    ("dunk", "Dunk Low", 115, 10, "#e5e5e5", [["#fff", "#1e7a46", "#fff"], ["#fff", "#111", "#fff"]]),
    ("af1", "Air Force 1", 125, 10, "#e8e0e9", [["#fff", "#fff", "#ddd"], ["#111", "#111", "#333"]]),
]
LOGIN_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()

ALLOWED_STATIC_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".png", ".jpg", ".jpeg",
    ".webp", ".svg", ".ico", ".txt", ".json", ".xml", ".woff2", ".woff"
}
FORBIDDEN_FILES = {
    "store_server.py", "swoosh.sqlite3", "README.md", "Dockerfile",
    "docker-compose.yml", "nginx.conf", ".env", ".gitignore", ".dockerignore"
}


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect_db():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE, timeout=15, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def init_db():
    with connect_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'staff')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                full_name TEXT,
                address TEXT,
                citizen_id TEXT,
                birth_date TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                csrf_token TEXT NOT NULL,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price INTEGER NOT NULL CHECK (price > 0),
                stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
                active INTEGER NOT NULL DEFAULT 1,
                bg TEXT NOT NULL,
                colors TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                order_number TEXT NOT NULL UNIQUE,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                total INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                size INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS staff_roles (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                permissions TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vouchers (
                code TEXT PRIMARY KEY COLLATE NOCASE,
                discount_type TEXT NOT NULL CHECK (discount_type IN ('percent', 'fixed')),
                discount_value INTEGER NOT NULL CHECK (discount_value > 0),
                min_total INTEGER NOT NULL DEFAULT 0 CHECK (min_total >= 0),
                starts_at TEXT,
                expires_at TEXT,
                usage_limit INTEGER,
                used_count INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                ip_address TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS loyalty_tiers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                min_points INTEGER NOT NULL UNIQUE CHECK (min_points >= 0),
                benefits TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS loyalty_accounts (
                id INTEGER PRIMARY KEY,
                phone TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS product_media (
                id INTEGER PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                alt_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        for column in ("full_name", "address", "citizen_id", "birth_date"):
            if column not in user_columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
        if "role_id" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES staff_roles(id)")
        order_columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
        for column, definition in (
            ("voucher_code", "TEXT"),
            ("discount", "INTEGER NOT NULL DEFAULT 0"),
            ("points_awarded", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in order_columns:
                db.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
        db.execute(
            "INSERT OR IGNORE INTO staff_roles (id, name, permissions) VALUES (1, 'Nhân viên bán hàng', ?)",
            (json.dumps(["orders.read", "orders.update"]),),
        )
        db.execute("UPDATE users SET role_id=1 WHERE role='staff' AND role_id IS NULL")
        db.executemany(
            "INSERT OR IGNORE INTO loyalty_tiers (name, min_points, benefits) VALUES (?, ?, ?)",
            [
                ("Đồng", 0, "Tích điểm cho mỗi đơn hàng hoàn tất."),
                ("Bạc", 500, "Ưu đãi dành cho khách hàng thân thiết."),
                ("Vàng", 1500, "Ưu đãi đặc biệt dành cho thành viên Vàng."),
            ],
        )
        db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS users_staff_citizen_id
               ON users(citizen_id) WHERE role='staff' AND citizen_id IS NOT NULL"""
        )
        for product_id, name, price, stock, bg, colors in INITIAL_PRODUCTS:
            db.execute(
                """INSERT OR IGNORE INTO products (id, name, price, stock, bg, colors)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (product_id, name, price, stock, bg, json.dumps(colors)),
            )
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))


def password_hash(password):
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${result.hex()}"


def password_matches(password, stored):
    try:
        algorithm, salt_hex, digest_hex = stored.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def validate_staff_profile(data, required=False):
    fields = ("full_name", "address", "citizen_id", "birth_date")
    profile = {}
    for field in fields:
        value = data.get(field)
        if value is None and not required:
            continue
        if not isinstance(value, str):
            raise ValueError("Vui lòng nhập đầy đủ họ tên, địa chỉ, số CCCD và ngày sinh.")
        value = value.strip()
        if field == "full_name" and not 2 <= len(value) <= 100:
            raise ValueError("Họ tên phải có từ 2 đến 100 ký tự.")
        if field == "address" and not 5 <= len(value) <= 200:
            raise ValueError("Địa chỉ phải có từ 5 đến 200 ký tự.")
        if field == "citizen_id" and not re.fullmatch(r"[0-9]{12}", value):
            raise ValueError("Số CCCD phải gồm đúng 12 chữ số.")
        if field == "birth_date":
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Ngày sinh không hợp lệ.") from exc
            if parsed_date.isoformat() != value or parsed_date < date(1900, 1, 1) or parsed_date > date.today():
                raise ValueError("Ngày sinh phải từ năm 1900 đến hiện tại.")
        profile[field] = value
    if required and len(profile) != len(fields):
        raise ValueError("Vui lòng nhập đầy đủ họ tên, địa chỉ, số CCCD và ngày sinh.")
    return profile


def create_user(username, password, role, profile=None, role_id=None):
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username):
        raise ValueError("Tên đăng nhập phải có 3–40 ký tự: chữ, số, dấu chấm, gạch ngang hoặc gạch dưới.")
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Mật khẩu phải có từ 12 đến 256 ký tự.")
    if role not in {"admin", "staff"}:
        raise ValueError("Vai trò tài khoản không hợp lệ.")
    profile = validate_staff_profile(profile or {}, required=role == "staff")
    with connect_db() as db:
        try:
            if role == "staff":
                role_id = 1 if role_id is None else role_id
                if not db.execute("SELECT 1 FROM staff_roles WHERE id=?", (role_id,)).fetchone():
                    raise ValueError("Vai trò nhân viên không tồn tại.")
            db.execute(
                """INSERT INTO users
                   (username, password_hash, role, created_at, full_name, address, citizen_id, birth_date, role_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    username, password_hash(password), role, datetime.now(timezone.utc).isoformat(),
                    profile.get("full_name"), profile.get("address"), profile.get("citizen_id"),
                    profile.get("birth_date"), role_id if role == "staff" else None,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise ValueError("Tên đăng nhập đã tồn tại.") from exc
            if role == "staff":
                raise ValueError("Số CCCD đã được sử dụng cho nhân viên khác.") from exc
            raise ValueError("Tên đăng nhập đã tồn tại.") from exc


def prompt_admin_passwords(gui=False):
    # 1. Environment variable
    env_pass = os.environ.get("SWOOSH_ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD")
    if env_pass:
        return env_pass

    # 2. Try Tkinter if explicitly requested and GUI is available
    if gui and os.environ.get("DISPLAY"):
        try:
            import tkinter as tk
            from tkinter import messagebox, simpledialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                p1 = simpledialog.askstring("Tạo tài khoản Admin", "Nhập mật khẩu (tối thiểu 12 ký tự):", show="*", parent=root)
                if not p1:
                    raise SystemExit("Đã hủy tạo tài khoản Admin.")
                p2 = simpledialog.askstring("Tạo tài khoản Admin", "Nhập lại mật khẩu để xác nhận:", show="*", parent=root)
                if not p2:
                    raise SystemExit("Đã hủy tạo tài khoản Admin.")
                if p1 != p2:
                    messagebox.showerror("Không khớp", "Hai mật khẩu không giống nhau.", parent=root)
                    raise SystemExit("Mật khẩu xác nhận không khớp.")
                return p1
            finally:
                root.destroy()
        except Exception:
            pass

    # 3. Terminal prompt (getpass)
    try:
        if sys.stdin.isatty():
            p1 = getpass.getpass("Nhập mật khẩu Admin (tối thiểu 12 ký tự): ")
            p2 = getpass.getpass("Nhập lại mật khẩu để xác nhận: ")
        else:
            p1 = sys.stdin.readline().strip()
            p2 = p1
        if p1 != p2:
            raise SystemExit("Mật khẩu xác nhận không khớp.")
        return p1
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("\nĐã hủy tạo tài khoản Admin.")


def product_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "price": row["price"],
        "stock": row["stock"],
        "active": bool(row["active"]),
        "bg": row["bg"],
        "colors": json.loads(row["colors"]),
    }


def order_json(db, row):
    items = db.execute(
        "SELECT product_id, product_name, size, quantity, unit_price FROM order_items WHERE order_id = ?",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "number": row["order_number"],
        "customerName": row["customer_name"],
        "phone": row["phone"],
        "address": row["address"],
        "note": row["note"],
        "total": row["total"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "voucherCode": row["voucher_code"],
        "discount": row["discount"],
        "items": [dict(item) for item in items],
    }


def record_activity(db, actor, action, entity, entity_id="", ip_address=""):
    db.execute(
        """INSERT INTO activity_logs
           (actor, action, entity, entity_id, created_at, ip_address)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (actor or "Khách", action, entity, str(entity_id), datetime.now(timezone.utc).isoformat(), ip_address),
    )


def voucher_discount(db, code, subtotal):
    if not code:
        return None, 0
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,30}", code.strip()):
        raise APIError(400, "Mã voucher không hợp lệ.")
    voucher = db.execute("SELECT * FROM vouchers WHERE code=? COLLATE NOCASE", (code.strip(),)).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if (
        not voucher or not voucher["active"]
        or (voucher["starts_at"] and voucher["starts_at"] > now)
        or (voucher["expires_at"] and voucher["expires_at"] < now)
        or (voucher["usage_limit"] is not None and voucher["used_count"] >= voucher["usage_limit"])
    ):
        raise APIError(400, "Voucher không tồn tại, đã hết hạn hoặc đã hết lượt sử dụng.")
    if subtotal < voucher["min_total"]:
        raise APIError(400, f"Đơn hàng cần đạt tối thiểu {voucher['min_total']:,} ₫ để dùng mã này.")
    discount = (
        subtotal * voucher["discount_value"] // 100
        if voucher["discount_type"] == "percent"
        else voucher["discount_value"]
    )
    return voucher, min(subtotal, discount)


def validate_voucher_data(data, code=None):
    code = code or data.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,30}", code.strip()):
        raise APIError(400, "Mã voucher phải gồm 3–30 ký tự chữ, số, gạch ngang hoặc gạch dưới.")
    discount_type = data.get("discountType")
    value = data.get("discountValue")
    min_total = data.get("minTotal", 0)
    usage_limit = data.get("usageLimit")
    active = data.get("active", True)
    if discount_type not in {"percent", "fixed"}:
        raise APIError(400, "Loại giảm giá không hợp lệ.")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise APIError(400, "Giá trị giảm giá phải là số nguyên dương.")
    if discount_type == "percent" and value > 100:
        raise APIError(400, "Mức giảm theo phần trăm không được vượt quá 100%.")
    if isinstance(min_total, bool) or not isinstance(min_total, int) or min_total < 0:
        raise APIError(400, "Giá trị đơn hàng tối thiểu không hợp lệ.")
    if usage_limit is not None and (
        isinstance(usage_limit, bool) or not isinstance(usage_limit, int) or usage_limit < 1
    ):
        raise APIError(400, "Giới hạn lượt sử dụng phải là số nguyên dương.")
    if not isinstance(active, bool):
        raise APIError(400, "Trạng thái voucher không hợp lệ.")
    parsed_dates = {}
    for field in ("startsAt", "expiresAt"):
        value_date = data.get(field) or None
        if value_date is not None:
            if not isinstance(value_date, str):
                raise APIError(400, "Thời hạn voucher không hợp lệ.")
            try:
                parsed = datetime.fromisoformat(value_date)
            except ValueError as exc:
                raise APIError(400, "Thời hạn voucher không hợp lệ.") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            value_date = parsed.astimezone(timezone.utc).isoformat()
        parsed_dates[field] = value_date
    if (
        parsed_dates["startsAt"] and parsed_dates["expiresAt"]
        and parsed_dates["startsAt"] >= parsed_dates["expiresAt"]
    ):
        raise APIError(400, "Ngày hết hạn phải sau ngày bắt đầu.")
    return {
        "code": code.strip().upper(),
        "discount_type": discount_type,
        "discount_value": value,
        "min_total": min_total,
        "starts_at": parsed_dates["startsAt"],
        "expires_at": parsed_dates["expiresAt"],
        "usage_limit": usage_limit,
        "active": int(active),
    }


class StoreHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'",
        )
        # Dynamic Cache-Control
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/images/"):
            self.send_header("Cache-Control", "public, max-age=604800, stale-while-revalidate=86400")
        elif path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        elif path in ("/robots.txt", "/sitemap.xml", "/favicon.ico"):
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def client_ip(self):
        if TRUST_PROXY:
            forwarded = self.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def send_json(self, status, payload, headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise APIError(400, "Độ dài dữ liệu không hợp lệ.") from exc
        if length < 1 or length > 1024 * 1024:
            raise APIError(413, "Dữ liệu gửi lên quá lớn hoặc bị thiếu.")
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise APIError(400, "Dữ liệu JSON không hợp lệ.") from exc
        if not isinstance(data, dict):
            raise APIError(400, "Dữ liệu gửi lên không hợp lệ.")
        return data

    def cookie_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookie.get("swoosh_session")
        return morsel.value if morsel else ""

    def current_session(self):
        token = self.cookie_token()
        if not token:
            return None
        with connect_db() as db:
            row = db.execute(
                """SELECT sessions.token_hash, sessions.csrf_token, sessions.user_id,
                          sessions.expires_at, users.username, users.role, users.active,
                          users.role_id
                   FROM sessions LEFT JOIN users ON users.id = sessions.user_id
                   WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
                (hashlib.sha256(token.encode()).hexdigest(), int(time.time())),
            ).fetchone()
        if not row:
            return None
        if row["user_id"] and not row["active"]:
            return None
        return row

    def make_session(self, user_id=None):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        expires = int(time.time()) + SESSION_SECONDS
        with connect_db() as db:
            db.execute(
                "INSERT INTO sessions (token_hash, csrf_token, user_id, expires_at) VALUES (?, ?, ?, ?)",
                (hashlib.sha256(token.encode()).hexdigest(), csrf, user_id, expires),
            )
        is_https = COOKIE_SECURE or (self.headers.get("X-Forwarded-Proto") == "https")
        cookie = f"swoosh_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_SECONDS}"
        if is_https:
            cookie += "; Secure"
        return csrf, cookie

    def require_csrf(self, session):
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, session["csrf_token"]):
            raise APIError(403, "Phiên gửi biểu mẫu hết hạn. Hãy tải lại trang rồi thử lại.")

    def require_role(self, *roles):
        session = self.current_session()
        if not session or not session["user_id"]:
            raise APIError(401, "Vui lòng đăng nhập.")
        if session["role"] not in roles:
            raise APIError(403, "Tài khoản không có quyền thực hiện thao tác này.")
        return session

    def require_permission(self, permission):
        session = self.require_role("admin", "staff")
        if session["role"] == "admin":
            return session
        if not session["role_id"]:
            raise APIError(403, "Tài khoản chưa được gán vai trò.")
        with connect_db() as db:
            row = db.execute(
                "SELECT permissions FROM staff_roles WHERE id=?",
                (session["role_id"],),
            ).fetchone()
        permissions = json.loads(row["permissions"]) if row else []
        if permission not in permissions:
            raise APIError(403, "Vai trò của bạn không có quyền thực hiện thao tác này.")
        return session

    def session_user(self, session):
        user = {"username": session["username"], "role": session["role"]}
        if session["role"] == "staff":
            with connect_db() as db:
                row = db.execute(
                    "SELECT permissions FROM staff_roles WHERE id=?",
                    (session["role_id"],),
                ).fetchone()
            user["permissions"] = json.loads(row["permissions"]) if row else []
        return user

    def login_rate_limited(self):
        now = time.monotonic()
        address = self.client_ip()
        with LOGIN_LOCK:
            attempts = [stamp for stamp in LOGIN_ATTEMPTS.get(address, []) if now - stamp < 300]
            LOGIN_ATTEMPTS[address] = attempts
            if len(attempts) >= 10:
                return True
            attempts.append(now)
        return False

    def do_HEAD(self):
        self.do_GET(head_only=True)

    def do_GET(self, head_only=False):
        path = unquote(urlsplit(self.path).path)
        try:
            # Health check endpoint
            if path in ("/api/health", "/healthz"):
                self.send_json(200, {"status": "ok", "time": datetime.now(timezone.utc).isoformat()})
                return

            # SEO: robots.txt
            if path == "/robots.txt":
                robots = (
                    "User-agent: *\n"
                    "Allow: /\n"
                    "Disallow: /api/\n"
                    "Disallow: /data/\n"
                    "Sitemap: /sitemap.xml\n"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(robots)))
                self.end_headers()
                if not head_only:
                    self.wfile.write(robots)
                return

            # SEO: sitemap.xml
            if path == "/sitemap.xml":
                sitemap = (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                    '  <url><loc>/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>\n'
                    '  <url><loc>/#collection</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>\n'
                    '  <url><loc>/#about</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>\n'
                    '  <url><loc>/#policies</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>\n'
                    '</urlset>\n'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(sitemap)))
                self.end_headers()
                if not head_only:
                    self.wfile.write(sitemap)
                return

            if path == "/api/session":
                session = self.current_session()
                if session:
                    self.send_json(200, {
                        "csrfToken": session["csrf_token"],
                        "user": (
                            self.session_user(session)
                            if session["user_id"] else None
                        ),
                    })
                else:
                    csrf, cookie = self.make_session()
                    self.send_json(200, {"csrfToken": csrf, "user": None}, {"Set-Cookie": cookie})
                return
            if path == "/api/products":
                with connect_db() as db:
                    rows = db.execute("SELECT * FROM products WHERE active = 1 ORDER BY name").fetchall()
                self.send_json(200, {"products": [product_json(row) for row in rows]})
                return
            if path == "/api/admin/products":
                self.require_role("admin")
                with connect_db() as db:
                    rows = db.execute("SELECT * FROM products ORDER BY name").fetchall()
                self.send_json(200, {"products": [product_json(row) for row in rows]})
                return
            if path == "/api/admin/users":
                self.require_role("admin")
                with connect_db() as db:
                    rows = db.execute(
                        """SELECT users.id, users.username, users.role, users.active, users.created_at,
                                  users.full_name, users.address, users.citizen_id, users.birth_date,
                                  users.role_id, staff_roles.name AS role_name
                           FROM users LEFT JOIN staff_roles ON staff_roles.id=users.role_id
                           ORDER BY users.role, users.username"""
                    ).fetchall()
                self.send_json(200, {"users": [dict(row) for row in rows]})
                return
            if path == "/api/admin/customers":
                self.require_role("admin")
                query = parse_qs(urlsplit(self.path).query)
                search = query.get("q", [""])[0].strip()
                with connect_db() as db:
                    rows = db.execute(
                        """WITH ranked_orders AS (
                               SELECT phone, customer_name, created_at,
                                      ROW_NUMBER() OVER (PARTITION BY phone ORDER BY id DESC) AS position
                               FROM orders
                           ),
                           customer_totals AS (
                               SELECT phone, COUNT(*) AS order_count,
                                      SUM(CASE WHEN status!='cancelled' THEN total ELSE 0 END) AS total_spent,
                                      MAX(created_at) AS last_order_at
                               FROM orders GROUP BY phone
                           )
                           SELECT totals.phone,
                                  ranked.customer_name AS full_name,
                                  totals.order_count,
                                  totals.total_spent,
                                  totals.last_order_at,
                                  COALESCE(accounts.points, 0) AS points,
                                  (SELECT name FROM loyalty_tiers
                                   WHERE min_points<=COALESCE(accounts.points, 0)
                                   ORDER BY min_points DESC LIMIT 1) AS tier_name
                           FROM customer_totals AS totals
                           JOIN ranked_orders AS ranked
                             ON ranked.phone=totals.phone AND ranked.position=1
                           LEFT JOIN loyalty_accounts AS accounts ON accounts.phone=totals.phone
                           WHERE (?='' OR totals.phone LIKE ? OR ranked.customer_name LIKE ?)
                           ORDER BY totals.last_order_at DESC LIMIT 500""",
                        (search, f"%{search}%", f"%{search}%"),
                    ).fetchall()
                self.send_json(200, {"customers": [dict(row) for row in rows]})
                return
            if path == "/api/admin/revenue":
                self.require_role("admin")
                query = parse_qs(urlsplit(self.path).query)
                start_text = query.get("from", [""])[0]
                end_text = query.get("to", [""])[0]
                try:
                    start_date = date.fromisoformat(start_text)
                    end_date = date.fromisoformat(end_text)
                except ValueError as exc:
                    raise APIError(400, "Ngày bắt đầu và ngày kết thúc không hợp lệ.") from exc
                if start_date.isoformat() != start_text or end_date.isoformat() != end_text:
                    raise APIError(400, "Ngày phải theo định dạng YYYY-MM-DD.")
                if end_date < start_date:
                    raise APIError(400, "Ngày kết thúc phải từ ngày bắt đầu trở đi.")
                vietnam_today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
                if end_date > vietnam_today:
                    raise APIError(400, "Ngày kết thúc không thể nằm trong tương lai.")
                if (end_date - start_date).days > 365:
                    raise APIError(400, "Mỗi lần thống kê chỉ hỗ trợ tối đa 366 ngày.")

                start_utc = (
                    datetime.combine(start_date, datetime.min.time()) - timedelta(hours=7)
                ).replace(tzinfo=timezone.utc).isoformat()
                end_utc = (
                    datetime.combine(end_date + timedelta(days=1), datetime.min.time())
                    - timedelta(hours=7)
                ).replace(tzinfo=timezone.utc).isoformat()
                with connect_db() as db:
                    summary = db.execute(
                        """SELECT
                               COALESCE(SUM(CASE WHEN status='completed' THEN total ELSE 0 END), 0)
                                   AS revenue,
                               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)
                                   AS completed_order_count,
                               COALESCE(AVG(CASE WHEN status='completed' THEN total END), 0)
                                   AS average_order_value,
                               COALESCE(SUM(CASE WHEN status IN ('confirmed','shipping')
                                                   THEN total ELSE 0 END), 0)
                                   AS in_progress_revenue,
                               SUM(CASE WHEN status IN ('confirmed','shipping') THEN 1 ELSE 0 END)
                                   AS in_progress_order_count
                           FROM orders
                           WHERE datetime(created_at)>=datetime(?) AND datetime(created_at)<datetime(?)""",
                        (start_utc, end_utc),
                    ).fetchone()
                    daily_rows = db.execute(
                        """SELECT date(created_at, '+7 hours') AS day,
                                  SUM(total) AS revenue, COUNT(*) AS order_count
                           FROM orders
                           WHERE status='completed'
                             AND datetime(created_at)>=datetime(?) AND datetime(created_at)<datetime(?)
                           GROUP BY date(created_at, '+7 hours')
                           ORDER BY day""",
                        (start_utc, end_utc),
                    ).fetchall()
                self.send_json(200, {
                    "from": start_text,
                    "to": end_text,
                    "revenue": summary["revenue"],
                    "completedOrderCount": summary["completed_order_count"] or 0,
                    "averageOrderValue": round(summary["average_order_value"] or 0),
                    "inProgressRevenue": summary["in_progress_revenue"],
                    "inProgressOrderCount": summary["in_progress_order_count"] or 0,
                    "daily": [dict(row) for row in daily_rows],
                })
                return
            if path == "/api/orders":
                self.require_permission("orders.read")
                query = parse_qs(urlsplit(self.path).query)
                search = query.get("q", [""])[0].strip()
                status = query.get("status", [""])[0]
                if status and status not in {"pending", "confirmed", "shipping", "completed", "cancelled"}:
                    raise APIError(400, "Trạng thái lọc không hợp lệ.")
                with connect_db() as db:
                    rows = db.execute(
                        """SELECT * FROM orders
                           WHERE (?='' OR status=?)
                             AND (?='' OR order_number LIKE ? OR customer_name LIKE ? OR phone LIKE ?)
                           ORDER BY id DESC LIMIT 500""",
                        (status, status, search, f"%{search}%", f"%{search}%", f"%{search}%"),
                    ).fetchall()
                    orders = [order_json(db, row) for row in rows]
                self.send_json(200, {"orders": orders})
                return
            if path == "/api/vouchers":
                with connect_db() as db:
                    rows = db.execute(
                        """SELECT code, discount_type, discount_value, min_total, starts_at, expires_at
                           FROM vouchers WHERE active=1 ORDER BY code"""
                    ).fetchall()
                self.send_json(200, {"vouchers": [dict(row) for row in rows]})
                return
            if path == "/api/size-chart":
                self.send_json(200, {"sizes": [
                    {"eu": 38, "us": "5.5", "uk": "5", "cm": 24},
                    {"eu": 39, "us": "6.5", "uk": "6", "cm": 24.5},
                    {"eu": 40, "us": "7", "uk": "6", "cm": 25},
                    {"eu": 41, "us": "8", "uk": "7", "cm": 26},
                    {"eu": 42, "us": "8.5", "uk": "7.5", "cm": 26.5},
                    {"eu": 43, "us": "9.5", "uk": "8.5", "cm": 27.5},
                    {"eu": 44, "us": "10", "uk": "9", "cm": 28},
                    {"eu": 45, "us": "11", "uk": "10", "cm": 29},
                ]})
                return
            if path == "/api/top-products":
                with connect_db() as db:
                    rows = db.execute(
                        """SELECT order_items.product_id AS id, order_items.product_name AS name,
                                  SUM(order_items.quantity) AS quantity,
                                  SUM(order_items.quantity * order_items.unit_price) AS revenue
                           FROM order_items JOIN orders ON orders.id=order_items.order_id
                           WHERE orders.status IN ('confirmed','shipping','completed')
                           GROUP BY order_items.product_id, order_items.product_name
                           ORDER BY quantity DESC, revenue DESC LIMIT 10"""
                    ).fetchall()
                self.send_json(200, {"products": [dict(row) for row in rows]})
                return
            if path == "/api/loyalty":
                query = parse_qs(urlsplit(self.path).query)
                phone = query.get("phone", [""])[0]
                order_number = query.get("order", [""])[0]
                if not re.fullmatch(r"[0-9]{9,12}", phone) or not re.fullmatch(r"SW-[A-F0-9]{8}", order_number):
                    raise APIError(400, "Nhập số điện thoại và mã đơn hàng hợp lệ.")
                with connect_db() as db:
                    verified = db.execute(
                        """SELECT 1 FROM orders
                           WHERE order_number=? AND phone=? AND status='completed'""",
                        (order_number, phone),
                    ).fetchone()
                    if not verified:
                        raise APIError(404, "Không tìm thấy đơn hàng hoàn tất khớp với thông tin này.")
                    account = db.execute(
                        "SELECT phone, full_name, points FROM loyalty_accounts WHERE phone=?",
                        (phone,),
                    ).fetchone()
                    tiers = db.execute(
                        "SELECT name, min_points, benefits FROM loyalty_tiers ORDER BY min_points"
                    ).fetchall()
                points = account["points"] if account else 0
                tier = next((item for item in reversed(tiers) if points >= item["min_points"]), None)
                self.send_json(200, {
                    "account": dict(account) if account else {"phone": phone, "full_name": "", "points": 0},
                    "tier": dict(tier) if tier else None,
                    "tiers": [dict(row) for row in tiers],
                })
                return
            if path == "/api/admin/vouchers":
                self.require_role("admin")
                with connect_db() as db:
                    rows = db.execute("SELECT * FROM vouchers ORDER BY code").fetchall()
                self.send_json(200, {"vouchers": [dict(row) for row in rows]})
                return
            if path == "/api/admin/logs":
                self.require_role("admin")
                query = parse_qs(urlsplit(self.path).query)
                search = query.get("q", [""])[0].strip()
                with connect_db() as db:
                    rows = db.execute(
                        """SELECT actor, action, entity, entity_id, created_at, ip_address
                           FROM activity_logs
                           WHERE ?='' OR actor LIKE ? OR action LIKE ? OR entity LIKE ? OR entity_id LIKE ?
                           ORDER BY id DESC LIMIT 500""",
                        (search, f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"),
                    ).fetchall()
                self.send_json(200, {"logs": [dict(row) for row in rows]})
                return
            if path == "/api/admin/roles":
                self.require_role("admin")
                with connect_db() as db:
                    rows = db.execute("SELECT * FROM staff_roles ORDER BY id").fetchall()
                self.send_json(200, {"roles": [
                    {**dict(row), "permissions": json.loads(row["permissions"])} for row in rows
                ]})
                return
            if path == "/api/admin/loyalty":
                self.require_role("admin")
                with connect_db() as db:
                    tiers = db.execute("SELECT * FROM loyalty_tiers ORDER BY min_points").fetchall()
                    accounts = db.execute(
                        "SELECT phone, full_name, points, created_at FROM loyalty_accounts ORDER BY points DESC LIMIT 500"
                    ).fetchall()
                self.send_json(200, {
                    "tiers": [dict(row) for row in tiers],
                    "accounts": [dict(row) for row in accounts],
                })
                return
            if path == "/api/admin/media":
                self.require_role("admin")
                with connect_db() as db:
                    rows = db.execute("SELECT * FROM product_media ORDER BY id DESC").fetchall()
                self.send_json(200, {"media": [
                    {**dict(row), "url": f"/images/products/{row['filename']}"} for row in rows
                ]})
                return
            if path.startswith("/api/"):
                raise APIError(404, "Không tìm thấy API này.")

            # Static file serving: Whitelist check
            if path in ("/", "/index.html", "/nike-store.html"):
                target_file = ROOT / "index.html"
                if not target_file.exists():
                    target_file = ROOT / "nike-store.html"
                self.path = f"/{target_file.name}"
            else:
                # Check for sensitive paths
                clean_path = path.lstrip("/")
                resolved = (ROOT / clean_path).resolve()
                if resolved != ROOT and ROOT not in resolved.parents:
                    raise APIError(404, "Không tìm thấy tệp tin.")
                
                # Block database, server scripts, and hidden files
                if (
                    "data" in resolved.parts
                    or "__pycache__" in resolved.parts
                    or resolved.name in FORBIDDEN_FILES
                    or resolved.suffix.lower() not in ALLOWED_STATIC_EXTENSIONS
                    or resolved.name.startswith(".")
                ):
                    raise APIError(404, "Không tìm thấy tệp tin.")

            if head_only:
                super().do_HEAD()
            else:
                super().do_GET()
        except APIError as exc:
            self.send_json(exc.status, {"error": exc.message})

    def do_POST(self):
        path = unquote(urlsplit(self.path).path)
        try:
            data = self.read_json()
            if path == "/api/login":
                session = self.current_session()
                if not session:
                    raise APIError(403, "Phiên đăng nhập hết hạn. Hãy tải lại trang.")
                self.require_csrf(session)
                if self.login_rate_limited():
                    raise APIError(429, "Bạn đã thử đăng nhập quá nhiều lần. Hãy chờ 5 phút.")
                username = str(data.get("username", "")).strip()
                password = data.get("password", "")
                if not isinstance(password, str) or len(username) > 40 or len(password) > 256:
                    raise APIError(400, "Tên đăng nhập hoặc mật khẩu không hợp lệ.")
                with connect_db() as db:
                    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                    valid = bool(user and user["active"] and password_matches(password, user["password_hash"]))
                if not valid:
                    with connect_db() as db:
                        record_activity(db, username or "Không rõ", "Đăng nhập thất bại", "auth", "", self.client_ip())
                    raise APIError(401, "Tên đăng nhập hoặc mật khẩu không đúng.")
                with connect_db() as db:
                    db.execute("DELETE FROM sessions WHERE token_hash = ?", (session["token_hash"],))
                csrf, cookie = self.make_session(user["id"])
                with connect_db() as db:
                    record_activity(db, user["username"], "Đăng nhập", "auth", "", self.client_ip())
                with LOGIN_LOCK:
                    LOGIN_ATTEMPTS.pop(self.client_ip(), None)
                self.send_json(
                    200,
                    {"csrfToken": csrf, "user": self.session_user({
                        "username": user["username"], "role": user["role"], "role_id": user["role_id"],
                    })},
                    {"Set-Cookie": cookie},
                )
                return
            if path == "/api/logout":
                session = self.current_session()
                if not session:
                    raise APIError(401, "Phiên đăng nhập đã hết hạn.")
                self.require_csrf(session)
                with connect_db() as db:
                    db.execute("DELETE FROM sessions WHERE token_hash = ?", (session["token_hash"],))
                    record_activity(db, session["username"], "Đăng xuất", "auth", "", self.client_ip())
                is_https = COOKIE_SECURE or (self.headers.get("X-Forwarded-Proto") == "https")
                expired = "swoosh_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
                if is_https:
                    expired += "; Secure"
                self.send_json(200, {"ok": True}, {"Set-Cookie": expired})
                return
            if path == "/api/orders":
                session = self.current_session()
                if not session:
                    raise APIError(403, "Phiên đặt hàng hết hạn. Hãy tải lại trang.")
                self.require_csrf(session)
                self.create_order(data)
                return
            if path == "/api/vouchers/check":
                session = self.current_session()
                if not session:
                    raise APIError(403, "Phiên kiểm tra voucher đã hết hạn. Hãy tải lại trang.")
                self.require_csrf(session)
                subtotal = data.get("subtotal")
                if isinstance(subtotal, bool) or not isinstance(subtotal, int) or subtotal < 0:
                    raise APIError(400, "Giá trị đơn hàng không hợp lệ.")
                with connect_db() as db:
                    voucher, discount = voucher_discount(db, data.get("code"), subtotal)
                self.send_json(200, {
                    "code": voucher["code"],
                    "discount": discount,
                    "total": subtotal - discount,
                })
                return
            if path == "/api/admin/vouchers":
                session = self.require_role("admin")
                self.require_csrf(session)
                voucher = validate_voucher_data(data)
                with connect_db() as db:
                    try:
                        db.execute(
                            """INSERT INTO vouchers
                               (code, discount_type, discount_value, min_total, starts_at, expires_at, usage_limit, active)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            tuple(voucher[key] for key in (
                                "code", "discount_type", "discount_value", "min_total",
                                "starts_at", "expires_at", "usage_limit", "active",
                            )),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise APIError(409, "Mã voucher đã tồn tại.") from exc
                    record_activity(db, session["username"], "Tạo voucher", "voucher", voucher["code"], self.client_ip())
                self.send_json(201, {"voucher": voucher})
                return
            if path == "/api/admin/roles":
                session = self.require_role("admin")
                self.require_csrf(session)
                name = data.get("name")
                permissions = data.get("permissions")
                allowed_permissions = {"orders.read", "orders.update"}
                if (
                    not isinstance(name, str) or not 2 <= len(name.strip()) <= 60
                    or not isinstance(permissions, list)
                    or any(permission not in allowed_permissions for permission in permissions)
                ):
                    raise APIError(400, "Tên vai trò hoặc danh sách quyền không hợp lệ.")
                with connect_db() as db:
                    try:
                        cursor = db.execute(
                            "INSERT INTO staff_roles (name, permissions) VALUES (?, ?)",
                            (name.strip(), json.dumps(sorted(set(permissions)))),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise APIError(409, "Tên vai trò đã tồn tại.") from exc
                    role_id = cursor.lastrowid
                    record_activity(db, session["username"], "Tạo vai trò", "role", role_id, self.client_ip())
                self.send_json(201, {"id": role_id, "name": name.strip(), "permissions": permissions})
                return
            if path == "/api/admin/loyalty/tiers":
                session = self.require_role("admin")
                self.require_csrf(session)
                name = data.get("name")
                min_points = data.get("minPoints")
                benefits = data.get("benefits", "")
                if (
                    not isinstance(name, str) or not 2 <= len(name.strip()) <= 40
                    or isinstance(min_points, bool) or not isinstance(min_points, int) or min_points < 0
                    or not isinstance(benefits, str) or len(benefits) > 200
                ):
                    raise APIError(400, "Thông tin hạng thành viên không hợp lệ.")
                with connect_db() as db:
                    try:
                        cursor = db.execute(
                            "INSERT INTO loyalty_tiers (name, min_points, benefits) VALUES (?, ?, ?)",
                            (name.strip(), min_points, benefits.strip()),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise APIError(409, "Tên hạng hoặc mốc điểm đã tồn tại.") from exc
                    record_activity(db, session["username"], "Tạo hạng thành viên", "loyalty_tier", cursor.lastrowid, self.client_ip())
                self.send_json(201, {"ok": True})
                return
            if path == "/api/admin/media":
                session = self.require_role("admin")
                self.require_csrf(session)
                data_url = data.get("dataUrl")
                alt_text = data.get("altText", "")
                if not isinstance(data_url, str) or not isinstance(alt_text, str) or len(alt_text) > 150:
                    raise APIError(400, "Thông tin ảnh không hợp lệ.")
                match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", data_url)
                if not match:
                    raise APIError(400, "Chỉ hỗ trợ ảnh PNG, JPEG hoặc WebP.")
                try:
                    image_bytes = base64.b64decode(match.group(2), validate=True)
                except ValueError as exc:
                    raise APIError(400, "Dữ liệu ảnh không hợp lệ.") from exc
                signatures = {
                    "png": (
                        image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
                        and len(image_bytes) >= 45
                        and image_bytes[12:16] == b"IHDR"
                        and image_bytes.endswith(b"IEND\xaeB`\x82")
                    ),
                    "jpeg": (
                        len(image_bytes) >= 20
                        and image_bytes.startswith(b"\xff\xd8\xff")
                        and image_bytes.endswith(b"\xff\xd9")
                    ),
                    "webp": (
                        image_bytes.startswith(b"RIFF")
                        and len(image_bytes) >= 30
                        and int.from_bytes(image_bytes[4:8], "little") == len(image_bytes) - 8
                        and image_bytes[8:12] == b"WEBP"
                    ),
                }
                if not image_bytes or len(image_bytes) > 700 * 1024 or not signatures[match.group(1)]:
                    raise APIError(400, "Ảnh vượt quá 700 KB hoặc định dạng tệp không khớp.")
                extension = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}[match.group(1)]
                filename = f"{secrets.token_hex(12)}{extension}"
                media_dir = ROOT / "images" / "products"
                media_dir.mkdir(parents=True, exist_ok=True)
                (media_dir / filename).write_bytes(image_bytes)
                with connect_db() as db:
                    db.execute(
                        "INSERT INTO product_media (filename, alt_text, created_at) VALUES (?, ?, ?)",
                        (filename, alt_text.strip(), datetime.now(timezone.utc).isoformat()),
                    )
                    record_activity(db, session["username"], "Tải ảnh sản phẩm", "media", filename, self.client_ip())
                self.send_json(201, {"filename": filename, "url": f"/images/products/{filename}"})
                return
            if path == "/api/admin/users":
                session = self.require_role("admin")
                self.require_csrf(session)
                username = data.get("username", "")
                password = data.get("password", "")
                if not isinstance(username, str) or not isinstance(password, str):
                    raise APIError(400, "Thông tin nhân viên không hợp lệ.")
                try:
                    role_id = data.get("roleId", 1)
                    if isinstance(role_id, bool) or not isinstance(role_id, int):
                        raise ValueError("Vai trò nhân viên không hợp lệ.")
                    create_user(username, password, "staff", data, role_id)
                except ValueError as exc:
                    raise APIError(400, str(exc)) from exc
                with connect_db() as db:
                    record_activity(db, session["username"], "Tạo tài khoản nhân viên", "user", username, self.client_ip())
                self.send_json(201, {"ok": True})
                return
            if path == "/api/admin/products":
                session = self.require_role("admin")
                self.require_csrf(session)
                product = self.validate_product(data)
                with connect_db() as db:
                    try:
                        db.execute(
                            """INSERT INTO products (id, name, price, stock, active, bg, colors)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                product["id"], product["name"], product["price"],
                                product["stock"], product["active"], product["bg"],
                                json.dumps(product["colors"]),
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise APIError(409, "Mã sản phẩm đã tồn tại.") from exc
                    record_activity(db, session["username"], "Thêm sản phẩm", "product", product["id"], self.client_ip())
                self.send_json(201, {"product": product})
                return
            raise APIError(404, "Không tìm thấy API này.")
        except APIError as exc:
            self.send_json(exc.status, {"error": exc.message})

    def do_PATCH(self):
        path = unquote(urlsplit(self.path).path)
        try:
            data = self.read_json()
            if path.startswith("/api/admin/vouchers/"):
                session = self.require_role("admin")
                self.require_csrf(session)
                code = path.rsplit("/", 1)[-1]
                voucher = validate_voucher_data(data, code)
                with connect_db() as db:
                    cursor = db.execute(
                        """UPDATE vouchers SET discount_type=?, discount_value=?, min_total=?,
                                  starts_at=?, expires_at=?, usage_limit=?, active=?
                           WHERE code=? COLLATE NOCASE""",
                        (
                            voucher["discount_type"], voucher["discount_value"], voucher["min_total"],
                            voucher["starts_at"], voucher["expires_at"], voucher["usage_limit"],
                            voucher["active"], code,
                        ),
                    )
                    if not cursor.rowcount:
                        raise APIError(404, "Không tìm thấy voucher.")
                    record_activity(db, session["username"], "Cập nhật voucher", "voucher", code, self.client_ip())
                self.send_json(200, {"ok": True})
                return
            if path.startswith("/api/admin/roles/"):
                session = self.require_role("admin")
                self.require_csrf(session)
                try:
                    role_id = int(path.rsplit("/", 1)[-1])
                except ValueError as exc:
                    raise APIError(400, "Vai trò không hợp lệ.") from exc
                name = data.get("name")
                permissions = data.get("permissions")
                allowed_permissions = {"orders.read", "orders.update"}
                if (
                    not isinstance(name, str) or not 2 <= len(name.strip()) <= 60
                    or not isinstance(permissions, list)
                    or any(permission not in allowed_permissions for permission in permissions)
                ):
                    raise APIError(400, "Tên vai trò hoặc danh sách quyền không hợp lệ.")
                with connect_db() as db:
                    try:
                        cursor = db.execute(
                            "UPDATE staff_roles SET name=?, permissions=? WHERE id=?",
                            (name.strip(), json.dumps(sorted(set(permissions))), role_id),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise APIError(409, "Tên vai trò đã tồn tại.") from exc
                    if not cursor.rowcount:
                        raise APIError(404, "Không tìm thấy vai trò.")
                    record_activity(db, session["username"], "Cập nhật vai trò", "role", role_id, self.client_ip())
                self.send_json(200, {"ok": True})
                return
            if path.startswith("/api/admin/loyalty/tiers/"):
                session = self.require_role("admin")
                self.require_csrf(session)
                try:
                    tier_id = int(path.rsplit("/", 1)[-1])
                except ValueError as exc:
                    raise APIError(400, "Hạng thành viên không hợp lệ.") from exc
                name = data.get("name")
                min_points = data.get("minPoints")
                benefits = data.get("benefits", "")
                if (
                    not isinstance(name, str) or not 2 <= len(name.strip()) <= 40
                    or isinstance(min_points, bool) or not isinstance(min_points, int) or min_points < 0
                    or not isinstance(benefits, str) or len(benefits) > 200
                ):
                    raise APIError(400, "Thông tin hạng thành viên không hợp lệ.")
                with connect_db() as db:
                    try:
                        existing = db.execute(
                            "SELECT min_points FROM loyalty_tiers WHERE id=?",
                            (tier_id,),
                        ).fetchone()
                        if not existing:
                            raise APIError(404, "Không tìm thấy hạng thành viên.")
                        if existing["min_points"] == 0 and min_points != 0:
                            raise APIError(409, "Hạng cơ bản phải giữ mốc 0 điểm.")
                        cursor = db.execute(
                            """UPDATE loyalty_tiers SET name=?, min_points=?, benefits=? WHERE id=?""",
                            (name.strip(), min_points, benefits.strip(), tier_id),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise APIError(409, "Tên hạng hoặc mốc điểm đã tồn tại.") from exc
                    if not cursor.rowcount:
                        raise APIError(404, "Không tìm thấy hạng thành viên.")
                    record_activity(db, session["username"], "Cập nhật hạng thành viên", "loyalty_tier", tier_id, self.client_ip())
                self.send_json(200, {"ok": True})
                return
            if path.startswith("/api/admin/products/"):
                session = self.require_role("admin")
                self.require_csrf(session)
                product_id = path.rsplit("/", 1)[-1]
                product = self.validate_product(data, product_id)
                with connect_db() as db:
                    existing = db.execute(
                        "SELECT active FROM products WHERE id=?",
                        (product_id,),
                    ).fetchone()
                    if not existing:
                        raise APIError(404, "Không tìm thấy sản phẩm.")
                    if existing["active"] and not product["active"]:
                        active_count = db.execute(
                            "SELECT COUNT(*) FROM products WHERE active=1"
                        ).fetchone()[0]
                        if active_count <= 1:
                            raise APIError(409, "Cần duy trì ít nhất một sản phẩm đang bán.")
                    cursor = db.execute(
                        """UPDATE products SET name=?, price=?, stock=?, active=?
                           WHERE id=?""",
                        (
                            product["name"], product["price"], product["stock"],
                            product["active"], product_id,
                        ),
                    )
                    record_activity(db, session["username"], "Cập nhật sản phẩm", "product", product_id, self.client_ip())
                if not cursor.rowcount:
                    raise APIError(404, "Không tìm thấy sản phẩm.")
                self.send_json(200, {"product": product})
                return
            if path.startswith("/api/admin/users/"):
                session = self.require_role("admin")
                self.require_csrf(session)
                try:
                    user_id = int(path.rsplit("/", 1)[-1])
                except ValueError as exc:
                    raise APIError(400, "Dữ liệu tài khoản không hợp lệ.") from exc
                profile_fields = {"full_name", "address", "citizen_id", "birth_date"}
                if not any(key in data for key in ("username", "password", "active", "roleId", *profile_fields)):
                    raise APIError(400, "Không có thông tin nào để cập nhật.")
                updates = []
                values = []
                if "username" in data:
                    username = data["username"]
                    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username.strip()):
                        raise APIError(400, "Tên đăng nhập phải có 3–40 ký tự hợp lệ.")
                    updates.append("username=?")
                    values.append(username.strip())
                if "password" in data and data["password"]:
                    password = data["password"]
                    if not isinstance(password, str) or not 12 <= len(password) <= 256:
                        raise APIError(400, "Mật khẩu mới phải có từ 12 đến 256 ký tự.")
                    updates.append("password_hash=?")
                    values.append(password_hash(password))
                if "active" in data:
                    active = data["active"]
                    if not isinstance(active, bool):
                        raise APIError(400, "Trạng thái tài khoản không hợp lệ.")
                    updates.append("active=?")
                    values.append(int(active))
                if "roleId" in data:
                    role_id = data["roleId"]
                    if isinstance(role_id, bool) or not isinstance(role_id, int):
                        raise APIError(400, "Vai trò nhân viên không hợp lệ.")
                    with connect_db() as db:
                        if not db.execute("SELECT 1 FROM staff_roles WHERE id=?", (role_id,)).fetchone():
                            raise APIError(400, "Vai trò nhân viên không tồn tại.")
                    updates.append("role_id=?")
                    values.append(role_id)
                try:
                    profile = validate_staff_profile(
                        {key: data[key] for key in profile_fields if key in data}
                    )
                except ValueError as exc:
                    raise APIError(400, str(exc)) from exc
                for field, value in profile.items():
                    updates.append(f"{field}=?")
                    values.append(value)
                if not updates:
                    raise APIError(400, "Hãy nhập tên đăng nhập, mật khẩu mới hoặc chọn trạng thái.")
                values.append(user_id)
                with connect_db() as db:
                    try:
                        cursor = db.execute(
                            f"UPDATE users SET {', '.join(updates)} WHERE id=? AND role='staff'",
                            values,
                        )
                    except sqlite3.IntegrityError as exc:
                        if "username" in data and db.execute(
                            "SELECT 1 FROM users WHERE username=? AND id!=?",
                            (str(data["username"]).strip(), user_id),
                        ).fetchone():
                            raise APIError(409, "Tên đăng nhập đã được sử dụng.") from exc
                        raise APIError(409, "Số CCCD đã được sử dụng cho nhân viên khác.") from exc
                    record_activity(db, session["username"], "Cập nhật nhân viên", "user", user_id, self.client_ip())
                if not cursor.rowcount:
                    raise APIError(404, "Không tìm thấy nhân viên.")
                if data.get("active") is False or ("password" in data and data["password"]):
                    with connect_db() as db:
                        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                self.send_json(200, {"ok": True})
                return
            if path.startswith("/api/orders/"):
                session = self.require_permission("orders.update")
                self.require_csrf(session)
                try:
                    order_id = int(path.rsplit("/", 1)[-1])
                    status = data["status"]
                except (ValueError, KeyError) as exc:
                    raise APIError(400, "Trạng thái đơn hàng không hợp lệ.") from exc
                transitions = {
                    "pending": {"confirmed", "cancelled"},
                    "confirmed": {"shipping", "cancelled"},
                    "shipping": {"completed", "cancelled"},
                    "completed": set(),
                    "cancelled": set(),
                }
                if status not in {"pending", "confirmed", "shipping", "completed", "cancelled"}:
                    raise APIError(400, "Trạng thái đơn hàng không hợp lệ.")
                with connect_db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    order = db.execute("SELECT status, phone, customer_name, total, points_awarded FROM orders WHERE id=?", (order_id,)).fetchone()
                    if not order:
                        raise APIError(404, "Không tìm thấy đơn hàng.")
                    if status not in transitions[order["status"]]:
                        raise APIError(409, "Không thể chuyển đơn hàng sang trạng thái này.")
                    if status == "cancelled":
                        items = db.execute(
                            "SELECT product_id, quantity FROM order_items WHERE order_id=?",
                            (order_id,),
                        ).fetchall()
                        for item in items:
                            db.execute(
                                "UPDATE products SET stock=stock+? WHERE id=?",
                                (item["quantity"], item["product_id"]),
                            )
                    db.execute(
                        "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                        (status, datetime.now(timezone.utc).isoformat(), order_id),
                    )
                    if status == "completed" and not order["points_awarded"]:
                        points = order["total"] // 10000
                        db.execute(
                            """INSERT INTO loyalty_accounts (phone, full_name, points, created_at)
                               VALUES (?, ?, ?, ?)
                               ON CONFLICT(phone) DO UPDATE SET
                                 full_name=excluded.full_name, points=loyalty_accounts.points+excluded.points""",
                            (
                                order["phone"], order["customer_name"], points,
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                        db.execute("UPDATE orders SET points_awarded=? WHERE id=?", (points, order_id))
                    record_activity(db, session["username"], "Cập nhật trạng thái đơn hàng", "order", order_id, self.client_ip())
                self.send_json(200, {"ok": True, "status": status})
                return
            raise APIError(404, "Không tìm thấy API này.")
        except APIError as exc:
            self.send_json(exc.status, {"error": exc.message})

    def do_DELETE(self):
        path = unquote(urlsplit(self.path).path)
        try:
            session = self.require_role("admin")
            self.require_csrf(session)
            if path.startswith("/api/admin/vouchers/"):
                code = path.rsplit("/", 1)[-1]
                with connect_db() as db:
                    cursor = db.execute("DELETE FROM vouchers WHERE code=? COLLATE NOCASE", (code,))
                    if not cursor.rowcount:
                        raise APIError(404, "Không tìm thấy voucher.")
                    record_activity(db, session["username"], "Xóa voucher", "voucher", code, self.client_ip())
                self.send_json(200, {"ok": True})
                return
            if path.startswith("/api/admin/roles/"):
                try:
                    role_id = int(path.rsplit("/", 1)[-1])
                except ValueError as exc:
                    raise APIError(400, "Vai trò không hợp lệ.") from exc
                if role_id == 1:
                    raise APIError(409, "Không thể xóa vai trò mặc định.")
                with connect_db() as db:
                    if db.execute("SELECT 1 FROM users WHERE role_id=? LIMIT 1", (role_id,)).fetchone():
                        raise APIError(409, "Hãy chuyển nhân viên sang vai trò khác trước khi xóa.")
                    cursor = db.execute("DELETE FROM staff_roles WHERE id=?", (role_id,))
                    if not cursor.rowcount:
                        raise APIError(404, "Không tìm thấy vai trò.")
                    record_activity(db, session["username"], "Xóa vai trò", "role", role_id, self.client_ip())
                self.send_json(200, {"ok": True})
                return
            if path.startswith("/api/admin/loyalty/tiers/"):
                try:
                    tier_id = int(path.rsplit("/", 1)[-1])
                except ValueError as exc:
                    raise APIError(400, "Hạng thành viên không hợp lệ.") from exc
                with connect_db() as db:
                    if db.execute("SELECT COUNT(*) FROM loyalty_tiers").fetchone()[0] <= 1:
                        raise APIError(409, "Cần duy trì ít nhất một hạng thành viên.")
                    tier = db.execute("SELECT min_points FROM loyalty_tiers WHERE id=?", (tier_id,)).fetchone()
                    if tier and tier["min_points"] == 0:
                        raise APIError(409, "Không thể xóa hạng cơ bản 0 điểm.")
                    cursor = db.execute("DELETE FROM loyalty_tiers WHERE id=?", (tier_id,))
                    if not cursor.rowcount:
                        raise APIError(404, "Không tìm thấy hạng thành viên.")
                    record_activity(db, session["username"], "Xóa hạng thành viên", "loyalty_tier", tier_id, self.client_ip())
                self.send_json(200, {"ok": True})
                return
            if path.startswith("/api/admin/media/"):
                filename = path.rsplit("/", 1)[-1]
                if not re.fullmatch(r"[a-f0-9]{24}\.(?:png|jpg|webp)", filename):
                    raise APIError(400, "Tệp media không hợp lệ.")
                with connect_db() as db:
                    cursor = db.execute("DELETE FROM product_media WHERE filename=?", (filename,))
                    if not cursor.rowcount:
                        raise APIError(404, "Không tìm thấy ảnh.")
                    record_activity(db, session["username"], "Xóa ảnh sản phẩm", "media", filename, self.client_ip())
                (ROOT / "images" / "products" / filename).unlink(missing_ok=True)
                self.send_json(200, {"ok": True})
                return
            raise APIError(404, "Không tìm thấy API này.")
        except APIError as exc:
            self.send_json(exc.status, {"error": exc.message})

    def create_order(self, data):
        name = data.get("name")
        phone = data.get("phone")
        address = data.get("address")
        note = data.get("note", "")
        items = data.get("items")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise APIError(400, "Vui lòng nhập họ tên hợp lệ.")
        if not isinstance(phone, str) or not re.fullmatch(r"[0-9]{9,12}", phone):
            raise APIError(400, "Số điện thoại cần có từ 9 đến 12 chữ số.")
        if not isinstance(address, str) or not 5 <= len(address.strip()) <= 200:
            raise APIError(400, "Vui lòng nhập địa chỉ nhận hàng hợp lệ.")
        if not isinstance(note, str) or len(note) > 500:
            raise APIError(400, "Ghi chú không hợp lệ.")
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            raise APIError(400, "Đơn hàng không có sản phẩm hợp lệ.")

        with connect_db() as db:
            db.execute("BEGIN IMMEDIATE")
            clean_items = []
            total = 0
            for item in items:
                if not isinstance(item, dict):
                    raise APIError(400, "Sản phẩm trong đơn không hợp lệ.")
                product_id = item.get("id")
                size = item.get("size")
                quantity = item.get("quantity")
                if (
                    not isinstance(product_id, str)
                    or size not in SIZES
                    or isinstance(quantity, bool)
                    or not isinstance(quantity, int)
                    or not 1 <= quantity <= 99
                ):
                    raise APIError(400, "Cỡ hoặc số lượng sản phẩm không hợp lệ.")
                product = db.execute(
                    "SELECT id, name, price, stock FROM products WHERE id=? AND active=1",
                    (product_id,),
                ).fetchone()
                if not product:
                    raise APIError(409, "Một sản phẩm trong giỏ không còn được bán.")
                if quantity > product["stock"]:
                    raise APIError(409, f"Sản phẩm {product['name']} không đủ tồn kho.")
                db.execute(
                    "UPDATE products SET stock=stock-? WHERE id=?",
                    (quantity, product_id),
                )
                line_total = product["price"] * quantity * 1000
                total += line_total
                clean_items.append((product["id"], product["name"], size, quantity, product["price"] * 1000))

            now = datetime.now(timezone.utc).isoformat()
            recent_duplicate = db.execute(
                """SELECT 1 FROM orders
                   WHERE phone=? AND created_at>=? AND status!='cancelled'
                   LIMIT 1""",
                (phone, (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()),
            ).fetchone()
            if recent_duplicate:
                raise APIError(429, "Đơn hàng vừa được gửi. Vui lòng chờ trước khi đặt thêm đơn.")
            voucher, discount = voucher_discount(db, data.get("voucherCode"), total)
            final_total = total - discount
            order_number = f"SW-{secrets.token_hex(4).upper()}"
            cursor = db.execute(
                """INSERT INTO orders
                   (order_number, customer_name, phone, address, note, total, status, created_at, updated_at,
                    voucher_code, discount)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
                (
                    order_number, name.strip(), phone, address.strip(), note.strip(),
                    final_total, now, now, voucher["code"] if voucher else None, discount,
                ),
            )
            order_id = cursor.lastrowid
            db.executemany(
                """INSERT INTO order_items
                   (order_id, product_id, product_name, size, quantity, unit_price)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(order_id, *item) for item in clean_items],
            )
            if voucher:
                db.execute("UPDATE vouchers SET used_count=used_count+1 WHERE code=?", (voucher["code"],))
            total_quantity = sum(item[3] for item in clean_items)
            record_activity(db, "Khách hàng", "Tạo đơn hàng", "order", order_number, self.client_ip())
            customer_orders = db.execute(
                "SELECT COUNT(*) FROM orders WHERE phone=? AND created_at>=?",
                (phone, (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()),
            ).fetchone()[0]
            if final_total >= 20_000_000 or total_quantity >= 10 or customer_orders > 3:
                record_activity(db, "Hệ thống", "Cảnh báo rủi ro đơn hàng", "order", order_number, self.client_ip())
        self.send_json(201, {
            "orderNumber": order_number,
            "subtotal": total,
            "discount": discount,
            "total": final_total,
            "status": "pending",
        })

    @staticmethod
    def validate_product(data, product_id=None):
        product_id = product_id or data.get("id")
        name = data.get("name")
        price = data.get("price")
        stock = data.get("stock")
        active = data.get("active", True)
        if not isinstance(product_id, str) or not re.fullmatch(r"[a-z0-9-]{2,40}", product_id):
            raise APIError(400, "Mã sản phẩm chỉ được gồm chữ thường, số và dấu gạch ngang.")
        if not isinstance(name, str) or not re.fullmatch(r"[\w\s.,'’()-]{2,100}", name.strip()):
            raise APIError(400, "Tên sản phẩm phải có từ 2 đến 100 ký tự.")
        if isinstance(price, bool) or not isinstance(price, int) or not 1 <= price <= 100000:
            raise APIError(400, "Giá sản phẩm phải từ 1 đến 100.000 (nghìn đồng).")
        if isinstance(stock, bool) or not isinstance(stock, int) or not 0 <= stock <= 100000:
            raise APIError(400, "Tồn kho phải từ 0 đến 100.000.")
        if not isinstance(active, bool):
            raise APIError(400, "Trạng thái sản phẩm không hợp lệ.")
        return {
            "id": product_id,
            "name": name.strip(),
            "price": price,
            "stock": stock,
            "active": int(active),
            "bg": "#e8e5df",
            "colors": [["#ffffff", "#111111", "#cccccc"]],
        }

    def translate_path(self, path):
        requested = unquote(urlsplit(path).path).lstrip("/")
        if not requested or requested in ("index.html", "nike-store.html"):
            target = ROOT / "index.html"
            if not target.exists():
                target = ROOT / "nike-store.html"
            return str(target)
        resolved = (ROOT / requested).resolve()
        if (
            (resolved != ROOT and ROOT not in resolved.parents)
            or resolved.name in FORBIDDEN_FILES
            or "data" in resolved.parts
            or "__pycache__" in resolved.parts
            or resolved.suffix.lower() not in ALLOWED_STATIC_EXTENSIONS
        ):
            return str(ROOT / "__not_found__")
        return str(resolved)


def main():
    parser = argparse.ArgumentParser(description="Swoosh Store Server")
    subparsers = parser.add_subparsers(dest="command")

    # Command: create-admin
    admin_parser = subparsers.add_parser("create-admin", help="Tạo tài khoản quản trị viên")
    admin_parser.add_argument("--username", "-u", help="Tên đăng nhập Admin")
    admin_parser.add_argument("--password", "-p", help="Mật khẩu Admin (tối thiểu 12 ký tự)")
    admin_parser.add_argument("--gui", action="store_true", help="Dùng hộp thoại đồ họa Tkinter để nhập mật khẩu")

    # Server options
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    parser.add_argument("--host", default=os.environ.get("SWOOSH_HOST", os.environ.get("HOST", default_host)), help="Địa chỉ IP lắng nghe (mặc định: 127.0.0.1 hoặc 0.0.0.0 trên Cloud)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", os.environ.get("SWOOSH_PORT", "8000"))), help="Cổng mạng (mặc định: 8000 hoặc $PORT)")

    args, unknown = parser.parse_known_args()
    init_db()

    if args.command == "create-admin":
        username = args.username or os.environ.get("SWOOSH_ADMIN_USERNAME") or os.environ.get("ADMIN_USERNAME")
        if not username:
            try:
                username = input("Admin username: ").strip()
            except (EOFError, KeyboardInterrupt):
                raise SystemExit("\nĐã hủy.")
        password = args.password or prompt_admin_passwords(gui=args.gui)
        try:
            create_user(username, password, "admin")
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Đã tạo tài khoản Admin '{username}' thành công. Bạn có thể đăng nhập ngay.")
        return

    server = ThreadingHTTPServer((args.host, args.port), StoreHandler)
    print(f"==================================================")
    print(f"  Swoosh Store đang chạy tại: http://{args.host}:{server.server_port}")
    print(f"  Trang chủ: http://{args.host}:{server.server_port}/")
    print(f"  Health Check: http://{args.host}:{server.server_port}/api/health")
    print(f"  Nhấn Ctrl+C để dừng máy chủ.")
    print(f"==================================================")

    def shutdown_handler(signum, frame):
        print("\nĐang dừng máy chủ an toàn...")
        server.server_close()
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, shutdown_handler)
    except (AttributeError, ValueError):
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang dừng máy chủ...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
