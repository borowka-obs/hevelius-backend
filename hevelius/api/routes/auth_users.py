"""Login, password reset, and user profile API routes."""

import logging
import secrets
from datetime import datetime, timezone

from flask import request
from flask.views import MethodView
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from flask_smorest import abort
from argon2.exceptions import VerifyMismatchError, InvalidHashError  # type: ignore[import-not-found]


from hevelius import db
from hevelius.passwords import password_hasher
from hevelius.user_admin_audit import log_user_admin_action
from hevelius.api.auth_utils import (
    PASSWORD_RESET_TOKEN_TTL,
    password_reset_token_hash,
    jwt_user_id_int,
    jwt_permissions_int,
    login_success_payload,
)
from hevelius.api.blueprint import blp
from hevelius.api.schemas import (
    LoginRequestSchema,
    LoginResponseSchema,
    PasswordResetCompleteBodySchema,
    PasswordResetTokenIssueResponseSchema,
    StatusMsgSchema,
    UserAdminDetailSchema,
    UserPasswordChangeSchema,
    UserProfileUpdateSchema,
    UsersAdminListResponseSchema,
    UsersAuditLogResponseSchema,
    UsersLoginsResponseSchema,
)

logger = logging.getLogger(__name__)


@blp.route("/login")
class LoginResource(MethodView):
    @blp.arguments(LoginRequestSchema)
    @blp.response(200, LoginResponseSchema)
    def post(self, login_data):
        """Login endpoint
        Returns user information and JWT token if credentials are valid
        """
        user = login_data.get('username')
        password = login_data.get('password')

        if user is None:
            return {'status': False, 'msg': 'Username not provided'}
        if password is None:
            return {'status': False, 'msg': 'Password not provided'}

        query = """SELECT user_id, pass_d, login, firstname, lastname, share, phone, email, permissions,
                aavso_id FROM users WHERE login=%s"""

        cnx = db.connect()
        db_resp = db.run_query(cnx, query, (user,))
        cnx.close()

        if not db_resp:
            print(f"Login: No such username ({user})")
            return {'status': False, 'msg': 'Invalid credentials'}

        user_id, pass_db, _, firstname, lastname, share, phone, email, permissions, aavso_id = db_resp[0]

        # Legacy: `pass_d` stored as MD5 hex (case-insensitive). Upgrade to argon2id lazily
        # after successful login.
        if pass_db is None:
            print(f"Login: Missing pass_d for user ({user})")
            return {'status': False, 'msg': 'Invalid credentials'}

        # Supported format: argon2id hash string (stored format is self-describing).
        if not (isinstance(pass_db, str) and pass_db.startswith("$argon2")):
            print(f"Login: Unsupported pass_d format for user ({user})")
            return {'status': False, 'msg': 'Invalid credentials'}

        try:
            password_hasher.verify(pass_db, password)
        except (VerifyMismatchError, InvalidHashError):
            print(f"Login: Invalid argon2id password for user ({user})")
            return {'status': False, 'msg': 'Invalid credentials'}

        # Future re-hashing: upgrade transparently if params are weak/changed.
        try:
            if password_hasher.check_needs_rehash(pass_db):
                pass_d_new = password_hasher.hash(password)
                cnx = db.connect()
                db.run_query(cnx, "UPDATE users SET pass_d=%s WHERE user_id=%s", (pass_d_new, user_id))
                cnx.close()
        except InvalidHashError:
            print(f"Login: Invalid argon2id hash for user ({user})")
            return {'status': False, 'msg': 'Invalid credentials'}

        # Create JWT access token
        access_token = create_access_token(
            identity=user_id,
            additional_claims={
                'permissions': permissions,
                'username': user
            }
        )

        print(f"User {user} logged in successfully, generated JWT token.")
        return login_success_payload(
            access_token, user_id, firstname, lastname, share, phone, email,
            permissions, aavso_id,
        )


@blp.route("/login/refresh")
class LoginRefreshResource(MethodView):
    @jwt_required()
    @blp.response(200, LoginResponseSchema)
    def post(self):
        """Issue a new access token for the current user (extends session on activity)."""
        user_id = get_jwt_identity()
        claims = get_jwt()
        access_token = create_access_token(
            identity=user_id,
            additional_claims={
                'permissions': claims.get('permissions'),
                'username': claims.get('username'),
            },
        )
        return {'status': True, 'token': access_token, 'user_id': int(user_id), 'msg': 'Token refreshed'}


@blp.route("/auth/password-reset")
class AuthPasswordResetResource(MethodView):
    @blp.arguments(PasswordResetCompleteBodySchema)
    @blp.response(200, StatusMsgSchema)
    def post(self, body):
        """Apply password reset using a token issued by an administrator."""
        token_hash = password_reset_token_hash(body["token"])
        cnx = db.connect()
        rows = db.run_query(
            cnx,
            """SELECT id, user_id FROM password_reset_tokens
               WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > now()""",
            (token_hash,),
        )
        if not rows:
            cnx.close()
            return {"status": False, "msg": "Invalid or expired reset token"}
        rid, user_id = rows[0]
        new_hash = password_hasher.hash(body["new_password"])
        db.run_query(cnx, "UPDATE users SET pass = NULL, pass_d = %s WHERE user_id = %s", (new_hash, user_id))
        db.run_query(
            cnx,
            "UPDATE password_reset_tokens SET consumed_at = now() WHERE id = %s",
            (rid,),
        )
        cnx.close()
        log_user_admin_action(
            "api",
            "auth.password_reset_complete",
            actor_user_id=None,
            target_user_id=user_id,
            details={},
        )
        return {"status": True, "msg": "Password updated"}


@blp.route("/users/me")
class UsersMeResource(MethodView):
    @jwt_required()
    @blp.response(200, UserAdminDetailSchema)
    def get(self):
        """Current user profile (from JWT); no password fields."""
        uid = jwt_user_id_int()
        if uid is None:
            abort(401, message="Invalid token identity")
        cnx = db.connect()
        rows = db.run_query(
            cnx,
            """SELECT user_id, login, firstname, lastname, share, phone, email, permissions,
                      aavso_id, pass_d
               FROM users WHERE user_id = %s""",
            (uid,),
        )
        cnx.close()
        if not rows:
            abort(404, message="User not found")
        r = rows[0]
        row_uid, login, fn, ln, share, phone, email, perm, aavso, pass_d = r
        return {
            "user_id": row_uid,
            "login": login,
            "firstname": fn,
            "lastname": ln,
            "share": float(share) if share is not None else None,
            "phone": phone,
            "email": email,
            "permissions": perm,
            "aavso_id": aavso,
            "login_enabled": bool(pass_d and str(pass_d).strip()),
        }

    @jwt_required()
    @blp.arguments(UserProfileUpdateSchema, location="json")
    @blp.response(200, UserAdminDetailSchema)
    def patch(self, body):
        """Update own profile: firstname, lastname, email (optional, may be empty), aavso_id."""
        uid = jwt_user_id_int()
        if uid is None:
            abort(401, message="Invalid token identity")
        cnx = db.connect()
        if not db.run_query(cnx, "SELECT user_id FROM users WHERE user_id = %s", (uid,)):
            cnx.close()
            abort(404, message="User not found")
        updates = []
        args = []
        for key in ("firstname", "lastname", "aavso_id"):
            if key in body:
                updates.append(f"{key} = %s")
                args.append(body[key] or None)
        if "email" in body:
            updates.append("email = %s")
            args.append(body["email"] if body["email"] else None)
        if updates:
            args.append(uid)
            db.run_query(cnx, "UPDATE users SET " + ", ".join(updates) + " WHERE user_id = %s", tuple(args))
        rows = db.run_query(
            cnx,
            """SELECT user_id, login, firstname, lastname, share, phone, email,
                      permissions, aavso_id, pass_d
               FROM users WHERE user_id = %s""",
            (uid,),
        )
        cnx.close()
        r = rows[0]
        return {
            "user_id": r[0], "login": r[1], "firstname": r[2], "lastname": r[3],
            "share": float(r[4]) if r[4] is not None else None,
            "phone": r[5], "email": r[6], "permissions": r[7], "aavso_id": r[8],
            "login_enabled": bool(r[9] and str(r[9]).strip()),
        }


@blp.route("/users/me/password")
class UsersMePasswordResource(MethodView):
    @jwt_required()
    @blp.arguments(UserPasswordChangeSchema, location="json")
    @blp.response(200, StatusMsgSchema)
    def post(self, body):
        """Change own password. current_password must match the stored credential."""
        uid = jwt_user_id_int()
        if uid is None:
            abort(401, message="Invalid token identity")
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT pass_d FROM users WHERE user_id = %s", (uid,))
        cnx.close()
        if not rows:
            abort(404, message="User not found")
        pass_d = rows[0][0]
        if not (pass_d and str(pass_d).strip()):
            abort(400, message="Account has no password set; use the password reset flow.")
        current = body["current_password"]
        if isinstance(pass_d, str) and _MD5_HEX_RE.fullmatch(pass_d):
            abort(400, message="Legacy password format detected; use the password reset flow.")
        elif isinstance(pass_d, str) and pass_d.startswith("$argon2"):
            try:
                password_hasher.verify(pass_d, current)
            except (VerifyMismatchError, InvalidHashError):
                abort(400, message="Current password is incorrect.")
        else:
            abort(400, message="Unsupported password format; use the password reset flow.")
        new_hash = password_hasher.hash(body["new_password"])
        cnx = db.connect()
        db.run_query(cnx, "UPDATE users SET pass = NULL, pass_d = %s WHERE user_id = %s", (new_hash, uid))
        cnx.close()
        log_user_admin_action("api", "user.password_change", actor_user_id=uid, target_user_id=uid, details={})
        return {"status": True, "msg": "Password updated"}


@blp.route("/users/audit-log")
class UsersAuditLogResource(MethodView):
    @jwt_required()
    @blp.response(200, UsersAuditLogResponseSchema)
    def get(self):
        """Recent user-administration audit entries (administrators only)."""
        if (jwt_permissions_int() & 1) == 0:
            abort(403, message="Administrator permission required (permissions bit 0).")
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(500, max(1, int(request.args.get("per_page", 50))))
        offset = (page - 1) * per_page
        cnx = db.connect()
        total = db.run_query(cnx, "SELECT count(*) FROM user_admin_audit")[0][0]
        rows = db.run_query(
            cnx,
            """SELECT id, created_at, channel, actor_user_id, action, target_user_id, details
               FROM user_admin_audit ORDER BY id DESC LIMIT %s OFFSET %s""",
            (per_page, offset),
        )
        cnx.close()
        entries = []
        for row in rows or []:
            rid, created_at, channel, actor_uid, action, target_uid, details = row
            entries.append({
                "id": rid,
                "created_at": created_at,
                "channel": channel,
                "actor_user_id": actor_uid,
                "action": action,
                "target_user_id": target_uid,
                "details": details if isinstance(details, dict) else None,
            })
        pages = (total + per_page - 1) // per_page if total else 0
        return {
            "entries": entries,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }


@blp.route("/users/logins")
class UsersLoginsResource(MethodView):
    @jwt_required()
    @blp.response(200, UsersLoginsResponseSchema)
    def get(self):
        """Compact user_id → login mapping for any authenticated user."""
        cnx = db.connect()
        rows = db.run_query(cnx, "SELECT user_id, login FROM users ORDER BY user_id")
        cnx.close()
        users = [{"user_id": r[0], "login": r[1]} for r in (rows or [])]
        return {"users": users}


@blp.route("/users/<int:user_id>/password-reset-token")
class UserPasswordResetTokenResource(MethodView):
    @jwt_required()
    @blp.response(200, PasswordResetTokenIssueResponseSchema)
    def post(self, user_id):
        """Issue a one-time password reset token for a user (administrators only)."""
        if (jwt_permissions_int() & 1) == 0:
            abort(403, message="Administrator permission required (permissions bit 0).")
        cnx = db.connect()
        row = db.run_query(cnx, "SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if not row:
            cnx.close()
            abort(404, message="User not found")
        db.run_query(
            cnx,
            "DELETE FROM password_reset_tokens WHERE user_id = %s AND consumed_at IS NULL",
            (user_id,),
        )
        raw = secrets.token_urlsafe(32)
        th = password_reset_token_hash(raw)
        expires_at = datetime.now(timezone.utc) + PASSWORD_RESET_TOKEN_TTL
        db.run_query(
            cnx,
            """INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
               VALUES (%s, %s, %s)""",
            (user_id, th, expires_at),
        )
        cnx.close()
        actor = jwt_user_id_int()
        log_user_admin_action(
            "api",
            "users.password_reset_token_issue",
            actor_user_id=actor,
            target_user_id=user_id,
            details={},
        )
        return {
            "status": True,
            "token": raw,
            "expires_at": expires_at,
            "user_id": user_id,
            "msg": "Deliver this token to the user securely; it is not stored in plaintext.",
        }


@blp.route("/users")
class UsersAdminListResource(MethodView):
    @jwt_required()
    @blp.response(200, UsersAdminListResponseSchema)
    def get(self):
        """Full user list without passwords; requires permissions bit 0 (administrator)."""
        if (jwt_permissions_int() & 1) == 0:
            abort(403, message="Administrator permission required (permissions bit 0).")
        log_user_admin_action(
            "api",
            "users.list_full",
            actor_user_id=jwt_user_id_int(),
            target_user_id=None,
            details={},
        )
        cnx = db.connect()
        rows = db.run_query(
            cnx,
            """SELECT user_id, login, firstname, lastname, share, phone, email, permissions,
                      aavso_id, pass_d
               FROM users ORDER BY user_id""",
        )
        cnx.close()
        users = []
        for r in rows or []:
            uid, login, fn, ln, share, phone, email, perm, aavso, pass_d = r
            users.append({
                "user_id": uid,
                "login": login,
                "firstname": fn,
                "lastname": ln,
                "share": float(share) if share is not None else None,
                "phone": phone,
                "email": email,
                "permissions": perm,
                "aavso_id": aavso,
                "login_enabled": bool(pass_d and str(pass_d).strip()),
            })
        return {"users": users}
