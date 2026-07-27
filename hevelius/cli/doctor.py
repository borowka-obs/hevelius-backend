"""
`hevelius doctor` - sanity checks for the local installation: config, DB
connectivity/schema, logs, and the JWT/web-url/SMTP settings that are easy
to leave at their example values.
"""

import re
import sys
from os import listdir
from os.path import isfile, join

from hevelius import db
from hevelius.cli.basic import hevelius_version
from hevelius.config import load_config
from hevelius.mailer import send_email

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"
INFO = "INFO"

_LABELS = {
    OK: "32",
    WARN: "33",
    FAIL: "31",
    INFO: "36",
}

_JWT_EXAMPLE_SECRET = "your-secret-key-here"
_WEB_EXAMPLE_URL = "https://hevelius.example.com"
_WEB_DEFAULT_URL = "http://localhost:3000"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LOG_ERROR_RE = re.compile(r"\b(ERROR|CRITICAL|Traceback)\b")
_LOG_TAIL_LINES = 2000


def _ansi(code, text, enabled):
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _print_check(name, status, message, color):
    tag = _ansi(_LABELS[status], f"[{status:>4}]", color)
    print(f"{tag} {name:<14} {message}")


def check_startup():
    """Verify the interpreter and core dependencies needed to run at all."""
    missing = []
    for mod in ("yaml", "argon2"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return FAIL, f"Missing required Python package(s): {', '.join(missing)}"
    return OK, f"Hevelius {hevelius_version() or 'unknown version'} starting fine (Python {sys.version.split()[0]})"


def check_config(config, meta):
    """Report where the configuration was loaded from."""
    if meta["base_source"] == "file":
        status = OK
        message = f"Loaded from {meta['base_config_path']}"
    else:
        status = WARN
        message = (
            "No hevelius.yaml found (expected at hevelius/hevelius.yaml); using built-in defaults. "
            "Copy hevelius/hevelius.yaml.example to hevelius/hevelius.yaml and edit it."
        )
    if meta["environment_overrides"]:
        message += f" Environment overrides: {', '.join(meta['environment_overrides'])}."
    return status, message


def check_database(config):
    """Try to connect to the configured database."""
    dbcfg = config["database"]
    where = f"{dbcfg['type']} database '{dbcfg['database']}' at {dbcfg['host']}:{dbcfg['port']} as {dbcfg['user']}"
    try:
        cnx = db.connect()
    except Exception as e:  # pylint: disable=broad-except
        return FAIL, f"Could not connect to {where}: {e}"
    cnx.close()
    return OK, f"Connected to {where}"


def latest_migration_version(schema_dir="db"):
    """Highest numbered *.psql migration script under schema_dir, or None."""
    try:
        entries = listdir(schema_dir)
    except OSError:
        return None

    versions = []
    for f in entries:
        if not isfile(join(schema_dir, f)) or not f.endswith("psql"):
            continue
        try:
            versions.append(int(f[:2]))
        except ValueError:
            continue
    return max(versions) if versions else None


def check_schema(db_ok):
    """Compare the DB schema_version against the newest migration script."""
    if not db_ok:
        return INFO, "Skipped (database unreachable)"

    latest = latest_migration_version()
    if latest is None:
        return WARN, "Could not determine the latest schema version from db/*.psql"

    try:
        cnx = db.connect()
        current = db.version_get(cnx)
        cnx.close()
    except Exception as e:  # pylint: disable=broad-except
        return FAIL, f"Could not read the DB schema version: {e}"

    if current == latest:
        return OK, f"DB schema is up to date (version {current})"
    if current < latest:
        return WARN, f"DB schema is version {current}, latest is {latest}; run 'hevelius db migrate'"
    return WARN, f"DB schema is version {current}, newer than the latest known migration ({latest})"


def check_logs(config):
    """Look for the gunicorn access/error logs at the configured path."""
    log_dir = (config.get("logs") or {}).get("path") or "/var/log/hevelius"
    found = [p for p in (join(log_dir, "error.log"), join(log_dir, "access.log")) if isfile(p)]
    if not found:
        return WARN, (
            f"No log files found in {log_dir} (expected error.log / access.log); "
            "set logs.path in config if logs live elsewhere."
        ), found
    return OK, f"Found: {', '.join(found)}", found


def check_log_errors(log_files):
    """Scan the tail of each log file for ERROR/CRITICAL/Traceback lines."""
    if not log_files:
        return INFO, "Skipped (no log files found)"

    details = []
    total = 0
    for path in log_files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-_LOG_TAIL_LINES:]
        except OSError as e:
            details.append(f"{path}: could not read ({e})")
            continue
        count = sum(1 for line in tail if _LOG_ERROR_RE.search(line))
        if count:
            total += count
            details.append(f"{path}: {count} error-like line(s) in the last {len(tail)} line(s)")

    if total == 0:
        return OK, "No errors found in the recent log lines"
    return WARN, "; ".join(details)


def check_jwt(config):
    """Make sure the JWT secret was changed from the example value."""
    secret = (config.get("jwt") or {}).get("secret-key")
    if not secret:
        return FAIL, "jwt.secret-key is not set; the API will refuse to start"
    if secret == _JWT_EXAMPLE_SECRET:
        return FAIL, "jwt.secret-key is still the example placeholder value; change it"
    if len(secret) < 32:
        return WARN, f"jwt.secret-key is only {len(secret)} character(s) long; use at least 32"
    return OK, "jwt.secret-key is set and differs from the example"


def check_web_url(config):
    """Make sure web.base-url was changed from the example/default value."""
    url = (config.get("web") or {}).get("base-url")
    if not url:
        return FAIL, "web.base-url is not set; links in emails (e.g. password reset) will be broken"
    if url == _WEB_EXAMPLE_URL:
        return WARN, f"web.base-url is still the example placeholder value ({url})"
    if url == _WEB_DEFAULT_URL:
        return WARN, f"web.base-url is still the built-in default ({url}); set it to your real frontend URL"
    return OK, f"web.base-url is set to {url}"


def check_smtp(config):
    """Sanity-check the SMTP settings without actually sending anything."""
    smtp = config.get("smtp") or {}
    host = smtp.get("host")
    if not host:
        return WARN, "smtp.host is not set; outgoing email will be logged instead of sent"

    problems = []

    try:
        port = int(smtp.get("port"))
        if not 1 <= port <= 65535:
            problems.append(f"port {smtp.get('port')} is out of range")
    except (TypeError, ValueError):
        problems.append(f"port {smtp.get('port')!r} is not a valid number")

    from_addr = smtp.get("from-addr")
    if not from_addr or not _EMAIL_RE.match(from_addr):
        problems.append(f"from-addr {from_addr!r} does not look like a valid email address")

    if bool(smtp.get("username")) != bool(smtp.get("password")):
        problems.append("username and password should both be set, or both left empty")

    if problems:
        return WARN, f"smtp.host={host}: " + "; ".join(problems)
    return OK, f"smtp.host={host}:{smtp.get('port')} looks sane (from-addr={from_addr})"


def mail_check(addr, color=True):
    """Send a real test email to addr using the configured SMTP settings."""
    print(f"Sending test email to {addr} ...")
    config = load_config()
    smtp = config.get("smtp") or {}

    if not smtp.get("host"):
        _print_check("Mail check", FAIL, "smtp.host is not set; there is nothing to test.", color)
        return 1

    try:
        sent = send_email(
            addr,
            "Hevelius doctor test email",
            "This is a test message sent by 'hevelius doctor --mail-check' to verify SMTP delivery.",
        )
    except Exception as e:  # pylint: disable=broad-except
        _print_check("Mail check", FAIL, f"Failed to send via {smtp['host']}:{smtp.get('port')}: {e}", color)
        return 1

    if sent:
        _print_check("Mail check", OK, f"Test email sent to {addr} via {smtp['host']}:{smtp.get('port')}", color)
        return 0

    _print_check("Mail check", FAIL, f"Test email to {addr} was not sent.", color)
    return 1


def doctor(args):
    """Run all `hevelius doctor` checks and print a report."""
    color = not getattr(args, "no_color", False)

    addr = getattr(args, "mail_check", None)
    if addr:
        return mail_check(addr, color)

    print("Hevelius Doctor")
    print("=" * 15)
    print()

    config, meta = load_config(return_metadata=True)

    results = [("Startup", *check_startup()), ("Configuration", *check_config(config, meta))]

    db_status, db_message = check_database(config)
    results.append(("Database", db_status, db_message))
    results.append(("DB schema", *check_schema(db_status == OK)))

    _log_status, log_message, log_files = check_logs(config)
    results.append(("Logs", _log_status, log_message))
    results.append(("Log errors", *check_log_errors(log_files)))

    results.append(("JWT secret", *check_jwt(config)))
    results.append(("Web URL", *check_web_url(config)))
    results.append(("SMTP", *check_smtp(config)))

    for name, status, message in results:
        _print_check(name, status, message, color)

    counts = {}
    for _, status, _msg in results:
        counts[status] = counts.get(status, 0) + 1
    fails = counts.get(FAIL, 0)
    warns = counts.get(WARN, 0)

    print()
    print(f"{len(results)} check(s): {counts.get(OK, 0)} OK, {warns} warning(s), {fails} failure(s).")
    if not fails and not warns:
        print("Everything looks good!")
    print()
    print("Tip: 'hevelius doctor --mail-check you@example.com' sends a real test email over SMTP.")

    return 1 if fails else 0
