"""
CLI commands for user management (list, add, enable, disable).
"""

from argon2 import PasswordHasher, Type  # type: ignore[import-not-found]

from hevelius import db
from hevelius.user_admin_audit import log_user_admin_action

_password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=1,
    type=Type.ID,
)


def _resolve_user(cnx, login_or_id):
    """Return (user_id, login) or None."""
    s = str(login_or_id).strip()
    if s.isdigit():
        rows = db.run_query(cnx, "SELECT user_id, login FROM users WHERE user_id = %s", (int(s),))
    else:
        rows = db.run_query(cnx, "SELECT user_id, login FROM users WHERE login = %s", (s,))
    return rows[0] if rows else None


def list_users():
    """Print all users (no password fields)."""
    cnx = db.connect()
    rows = db.run_query(
        cnx,
        """SELECT user_id, login, firstname, lastname, share, phone, email, permissions,
                  aavso_id, pass_d
           FROM users ORDER BY user_id""",
    )
    cnx.close()
    if not rows:
        print("No users found.")
        return
    print(
        f"{'ID':<6} {'Login':<12} {'Name':<28} {'Email':<28} "
        f"{'Perm':<5} {'Login OK':<8} AAVSO"
    )
    print("-" * 110)
    for r in rows:
        uid, login, fn, ln, share, phone, email, perm, aavso, pass_d = r
        can_login = bool(pass_d and str(pass_d).strip())
        name = f"{fn or ''} {ln or ''}".strip()[:26]
        login_s = (login or "")[:10]
        email_s = (email or "")[:26]
        print(
            f"{uid:<6} {login_s:<12} {name:<28} {email_s:<28} "
            f"{perm!s:<5} {str(can_login):<8} {aavso or ''}"
        )


def add_user(
    login,
    password,
    firstname=None,
    lastname=None,
    share=None,
    phone=None,
    email=None,
    permissions=0,
    aavso_id=None,
):
    """Create a user with argon2id hash in pass_d. Returns user_id or None."""
    login = (login or "").strip()
    if not login:
        print("Error: login is required.")
        return None
    if not password:
        print("Error: password is required.")
        return None
    pass_d = _password_hasher.hash(password)
    cnx = db.connect()
    if db.run_query(cnx, "SELECT 1 FROM users WHERE login = %s", (login,)):
        cnx.close()
        print(f"Error: login '{login}' already exists.")
        return None
    try:
        db.run_query(
            cnx,
            """INSERT INTO users (login, pass, pass_d, firstname, lastname, share, phone, email,
                                  permissions, aavso_id)
               VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                login,
                pass_d,
                firstname,
                lastname,
                share,
                phone,
                email,
                permissions,
                aavso_id,
            ),
        )
    except Exception as e:
        cnx.close()
        err = str(e).lower()
        if "unique" in err or "duplicate" in err:
            print(f"Error: login '{login}' already exists.")
        else:
            print(f"Error: {e}")
        return None
    row = db.run_query(cnx, "SELECT user_id FROM users WHERE login = %s", (login,))
    cnx.close()
    uid = row[0][0] if row else None
    if uid is None:
        print("Error: failed to read new user_id.")
        return None
    log_user_admin_action(
        "cli", "user.add", actor_user_id=None, target_user_id=uid, details={"login": login}
    )
    print(f"Created user_id={uid} login={login}")
    return uid


def disable_user(login_or_id):
    """Clear pass and pass_d so the user cannot log in."""
    cnx = db.connect()
    row = _resolve_user(cnx, login_or_id)
    if not row:
        cnx.close()
        print(f"User not found: {login_or_id!r}")
        return False
    uid, login = row
    db.run_query(cnx, "UPDATE users SET pass = NULL, pass_d = NULL WHERE user_id = %s", (uid,))
    cnx.close()
    log_user_admin_action(
        "cli",
        "user.disable",
        actor_user_id=None,
        target_user_id=uid,
        details={"login": login},
    )
    print(f"Disabled user_id={uid} login={login!r} (password cleared).")
    return True


def enable_user(login_or_id, password):
    """Set pass_d from password; clears legacy pass."""
    if not password:
        print("Error: password is required to enable a user.")
        return False
    pass_d = _password_hasher.hash(password)
    cnx = db.connect()
    row = _resolve_user(cnx, login_or_id)
    if not row:
        cnx.close()
        print(f"User not found: {login_or_id!r}")
        return False
    uid, login = row
    db.run_query(
        cnx,
        "UPDATE users SET pass = NULL, pass_d = %s WHERE user_id = %s",
        (pass_d, uid),
    )
    cnx.close()
    log_user_admin_action(
        "cli",
        "user.enable",
        actor_user_id=None,
        target_user_id=uid,
        details={"login": login},
    )
    print(f"Enabled user_id={uid} login={login!r} (password set).")
    return True
