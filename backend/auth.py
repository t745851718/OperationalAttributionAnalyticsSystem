import hashlib
import hmac
import os
import secrets
import time

import jwt

from backend.config import RUNTIME

ROLES = {"analyst", "manager", "admin"}
DEMO_USERS = {
    "analyst": ("analyst-demo-2025", "analyst", ["ecommerce", "fmcg"]),
    "manager": ("manager-demo-2025", "manager", ["ecommerce"]),
    "admin": ("admin-demo-2025", "admin", ["ecommerce", "fmcg"]),
}


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1)
    return f"{salt}:{derived.hex()}"


def matches(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(":", 1)[0]), stored)


def signing_key():
    if key := os.getenv("JWT_SECRET"):
        if len(key) < 32:
            raise ValueError("JWT_SECRET 至少需要 32 个字符")
        return key
    path = RUNTIME / "jwt.key"
    RUNTIME.mkdir(parents=True, exist_ok=True)
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            stream.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return path.read_text().strip()


def issue(username, key):
    timestamp = int(time.time())
    return jwt.encode(
        {"sub": username, "iat": timestamp, "exp": timestamp + 8 * 3600, "iss": "attribution"},
        key, algorithm="HS256",
    )
