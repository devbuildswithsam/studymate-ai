"""SMA-56 spike: do the self-built auth libraries behave the way ADR-0009 assumes?

Throwaway code, not part of the app. Run from this folder with its own venv:
    py -3.12 -m venv .venv
    .venv\\Scripts\\activate
    pip install -r requirements.txt
    python spike.py
"""

import base64
import json
import time
from datetime import UTC, datetime, timedelta

import jwt  # PyJWT
from pwdlib import PasswordHash

SECRET = "spike-only-secret-at-least-32-bytes-long!!"  # the app reads it from .env


def check(name: str, ok: bool) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")


# --- 1. Password hashing: pwdlib with Argon2 (FastAPI docs' recommendation) --------------
hasher = PasswordHash.recommended()

start = time.perf_counter()
stored = hasher.hash("correct horse battery staple")
seconds = time.perf_counter() - start
print(f"one Argon2 hash took {seconds * 1000:.0f} ms")
print(f"stored form: {stored[:30]}...  (algorithm, settings and salt live in the string)")

check("the right password verifies", hasher.verify("correct horse battery staple", stored))
check("a wrong password fails", not hasher.verify("correct horse battery stapl", stored))
check(
    "the same password hashes differently each time (random salt)",
    hasher.hash("same") != hasher.hash("same"),
)

# --- 2. Tokens: PyJWT, HS256 -------------------------------------------------------------
now = datetime.now(UTC)
token = jwt.encode({"sub": "user-123", "iat": now, "exp": now + timedelta(hours=8)}, SECRET)
claims = jwt.decode(token, SECRET, algorithms=["HS256"])
check("a valid token decodes to its user", claims["sub"] == "user-123")


def rejected(bad_token: str) -> bool:
    try:
        jwt.decode(bad_token, SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return True
    return False


expired = jwt.encode({"sub": "user-123", "exp": now - timedelta(seconds=1)}, SECRET)
check("an expired token is rejected", rejected(expired))

check(
    "a token signed with another secret is rejected",
    rejected(jwt.encode({"sub": "x"}, "other-" * 6)),
)

# Change the user inside the token but keep the old signature.
header, payload, signature = token.split(".")
evil = json.loads(base64.urlsafe_b64decode(payload + "=="))
evil["sub"] = "admin"
evil_payload = base64.urlsafe_b64encode(json.dumps(evil).encode()).rstrip(b"=").decode()
check("a tampered token is rejected", rejected(f"{header}.{evil_payload}.{signature}"))

# The classic attack: "alg": "none" and no signature at all.
none_token = jwt.encode({"sub": "admin"}, key=None, algorithm="none")
check('an "alg: none" token is rejected', rejected(none_token))
