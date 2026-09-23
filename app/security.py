import base64, hashlib, hmac, os, struct, time, urllib.parse
from fastapi import Request
from sqlalchemy.orm import Session
from app.models import User

ITERATIONS = 210_000

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )

def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt_b64, digest_b64 = encoded.split("$", 3)
        if algo != "pbkdf2_sha256": return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def current_user(request: Request, db: Session):
    uid = request.session.get("user_id")
    if not uid:
        return None
    user=db.get(User, uid)
    if not user or not user.active:
        request.session.clear()
        return None
    return user


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")

def _totp_code(secret: str, counter: int, digits: int = 6) -> str:
    padded=secret.upper()+("="*((8-len(secret)%8)%8))
    key=base64.b32decode(padded,casefold=True)
    msg=struct.pack(">Q",counter)
    digest=hmac.new(key,msg,hashlib.sha1).digest()
    offset=digest[-1]&0x0F
    num=(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%(10**digits)
    return str(num).zfill(digits)

def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    if not secret or not code or not code.isdigit(): return False
    counter=int(time.time())//30
    return any(hmac.compare_digest(_totp_code(secret,counter+i),code.zfill(6)) for i in range(-window,window+1))

def totp_uri(secret: str, username: str, issuer: str = "FMTS") -> str:
    label=urllib.parse.quote(f"{issuer}:{username}")
    params=urllib.parse.urlencode({"secret":secret,"issuer":issuer,"digits":6,"period":30})
    return f"otpauth://totp/{label}?{params}"
