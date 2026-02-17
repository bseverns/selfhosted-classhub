"""Cross-service student event hooks written into Class Hub tables.

This helper service shares the same database in deployment, so it can append
`helper_chat_access` rows into `hub_studentevent` using a best-effort insert.
"""

from __future__ import annotations

import json
import logging

from django.db import connection

logger = logging.getLogger(__name__)


def emit_helper_chat_access_event(
    *,
    classroom_id: int | None,
    student_id: int | None,
    ip_address: str,
    details: dict,
) -> None:
    """Best-effort append into classhub student events table."""
    if not classroom_id and not student_id:
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO hub_studentevent
                    (classroom_id, student_id, event_type, source, details, ip_address, created_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                [
                    classroom_id or None,
                    student_id or None,
                    "helper_chat_access",
                    "homework_helper.chat",
                    json.dumps(details or {}),
                    ip_address or None,
                ],
            )
    except Exception:
        logger.exception("helper_chat_student_event_write_failed")
