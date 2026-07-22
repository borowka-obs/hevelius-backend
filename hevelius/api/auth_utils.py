"""JWT and auth helpers for the Hevelius REST API."""
import hashlib
import re
from datetime import timedelta

from flask_jwt_extended import get_jwt, get_jwt_identity

_MD5_HEX_RE = re.compile(r"^[a-fA-F0-9]{32}$")

PASSWORD_RESET_TOKEN_TTL = timedelta(hours=1)


def normalize_jwt_secret(secret: str) -> str:
    """Pad short HS256 secrets via SHA-256 for PyJWT >= 2.10."""
    secret_bytes = secret.encode("utf-8")
    if len(secret_bytes) < 32:
        return hashlib.sha256(secret_bytes).hexdigest()
    return secret


def jwt_identity_to_string(identity):
    """PyJWT >= 2.10 requires sub claim to be a string."""
    return str(identity)


def password_reset_token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def jwt_user_id_int():
    ident = get_jwt_identity()
    try:
        return int(ident)
    except (TypeError, ValueError):
        return None


def jwt_permissions_int():
    claims = get_jwt()
    p = claims.get("permissions")
    if p is None:
        return 0
    try:
        return int(p)
    except (TypeError, ValueError):
        return 0


def login_success_payload(access_token, user_id, firstname, lastname, share, phone, email,
                          permissions, aavso_id, username):
    return {
        "status": True,
        "token": access_token,
        "user_id": user_id,
        "firstname": firstname,
        "lastname": lastname,
        "share": share,
        "phone": phone,
        "email": email,
        "permissions": permissions,
        "aavso_id": aavso_id,
        "msg": "Welcome",
    }


# Backwards-compatible private aliases (used by routes during migration)
_normalize_jwt_secret = normalize_jwt_secret
_jwt_identity_to_string = jwt_identity_to_string
_password_reset_token_hash = password_reset_token_hash
_jwt_user_id_int = jwt_user_id_int
_jwt_permissions_int = jwt_permissions_int
_login_success_payload = login_success_payload
