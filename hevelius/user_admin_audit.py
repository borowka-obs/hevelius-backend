"""
Append-only audit log for user administration (API and CLI).
"""

import json

from hevelius import db


def log_user_admin_action(channel, action, actor_user_id=None, target_user_id=None, details=None):
    """
    Insert one audit row. channel is 'api' or 'cli'. details is JSON-serializable dict.
    """
    cnx = db.connect()
    try:
        db.run_query(
            cnx,
            """INSERT INTO user_admin_audit (channel, actor_user_id, action, target_user_id, details)
               VALUES (%s, %s, %s, %s, %s::jsonb)""",
            (
                channel,
                actor_user_id,
                action,
                target_user_id,
                json.dumps(details if details is not None else {}),
            ),
        )
    finally:
        cnx.close()
