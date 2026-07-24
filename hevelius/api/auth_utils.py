"""JWT and auth helpers for the Hevelius REST API."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask_jwt_extended import get_jwt, get_jwt_identity

from hevelius import db

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
    """SHA-256 hex digest of a password-reset token for DB storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_password_reset_token(cnx, user_id: int):
    """Invalidate any pending reset tokens for user_id and issue a new one.

    Returns (raw_token, expires_at); the raw token is only ever available here.
    """
    db.run_query(
        cnx,
        "DELETE FROM password_reset_tokens WHERE user_id = %s AND consumed_at IS NULL",
        (user_id,),
    )
    raw = secrets.token_urlsafe(32)
    token_hash = password_reset_token_hash(raw)
    expires_at = datetime.now(timezone.utc) + PASSWORD_RESET_TOKEN_TTL
    db.run_query(
        cnx,
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (user_id, token_hash, expires_at),
    )
    return raw, expires_at


def jwt_user_id_int():
    """Return the JWT subject as an int user_id, or None if missing/invalid."""
    ident = get_jwt_identity()
    try:
        return int(ident)
    except (TypeError, ValueError):
        return None


def jwt_permissions_int():
    """Return the permissions claim as an int (default 0)."""
    claims = get_jwt()
    p = claims.get("permissions")
    if p is None:
        return 0
    try:
        return int(p)
    except (TypeError, ValueError):
        return 0


def login_success_payload(access_token, user_id, firstname, lastname, share, phone, email,
                          permissions, aavso_id):
    """Build the JSON body returned by successful login / token refresh."""
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
