"""Queries against the Synapse PostgreSQL database."""

from __future__ import annotations

import asyncpg


async def get_joined_rooms(pool: asyncpg.Pool, matrix_user_id: str) -> list[str]:
    """Return room_ids where *matrix_user_id* currently has membership='join'.

    Uses local_current_membership which stores one row per (room_id, user_id)
    with the current membership state, avoiding duplicates from historical events.
    """
    rows = await pool.fetch(
        """
        SELECT room_id
        FROM local_current_membership
        WHERE user_id = $1
          AND membership = 'join'
        ORDER BY room_id
        """,
        matrix_user_id,
    )
    return [r["room_id"] for r in rows]


async def get_rooms_metadata(
    pool: asyncpg.Pool,
    room_ids: list[str],
) -> dict[str, dict]:
    """Fetch room name, avatar, member count for a list of rooms.

    Uses Synapse's pre-computed room_stats_state and room_stats_current tables
    instead of scanning events, which is both faster and more reliable.

    Returns {room_id: {name, avatar_mxc, members_count}}.
    """
    if not room_ids:
        return {}

    rows = await pool.fetch(
        """
        SELECT
            r.room_id,
            rss.name,
            rss.avatar AS avatar_mxc,
            COALESCE(rsc.joined_members, 0) AS members_count
        FROM rooms r
        LEFT JOIN room_stats_state rss ON rss.room_id = r.room_id
        LEFT JOIN room_stats_current rsc ON rsc.room_id = r.room_id
        WHERE r.room_id = ANY($1)
        """,
        room_ids,
    )
    result = {}
    for row in rows:
        result[row["room_id"]] = {
            "name": row["name"],
            "avatar_mxc": row["avatar_mxc"],
            "members_count": row["members_count"] or 0,
        }
    return result


async def get_last_messages(
    pool: asyncpg.Pool,
    room_ids: list[str],
) -> dict[str, dict]:
    """Fetch last message per room.

    Returns {room_id: {sender, body, timestamp}}.
    """
    if not room_ids:
        return {}

    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (e.room_id)
            e.room_id,
            e.sender,
            e.origin_server_ts AS timestamp,
            ej.json::json->'content'->>'body' AS body,
            ej.json::json->'content'->>'msgtype' AS msgtype
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = ANY($1)
          AND e.type = 'm.room.message'
          AND e.outlier = false
        ORDER BY e.room_id, e.origin_server_ts DESC
        """,
        room_ids,
    )
    result = {}
    for row in rows:
        body = row["body"] or ""
        msgtype = row["msgtype"] or "m.text"
        if msgtype == "m.image":
            body = body or "[Image]"
        elif msgtype == "m.file":
            body = body or "[File]"
        elif msgtype == "m.video":
            body = body or "[Video]"
        elif msgtype == "m.audio":
            body = body or "[Audio]"

        result[row["room_id"]] = {
            "sender": row["sender"],
            "body": body,
            "timestamp": row["timestamp"],
        }
    return result


async def get_unread_counts(
    pool: asyncpg.Pool,
    room_ids: list[str],
    matrix_user_id: str,
) -> dict[str, int]:
    """Fetch unread message count per room for a given user.

    Uses the read-receipt marker: count messages after the last receipt.
    """
    if not room_ids:
        return {}

    rows = await pool.fetch(
        """
        SELECT
            e.room_id,
            COUNT(*) AS unread
        FROM events e
        WHERE e.room_id = ANY($1)
          AND e.type = 'm.room.message'
          AND e.outlier = false
          AND e.origin_server_ts > COALESCE(
              (SELECT MAX(e2.origin_server_ts)
               FROM receipts_linearized rl
               JOIN events e2 ON e2.event_id = rl.event_id
               WHERE rl.room_id = e.room_id
                 AND rl.user_id = $2
                 AND rl.receipt_type = 'm.read'),
              0
          )
          AND e.sender != $2
        GROUP BY e.room_id
        """,
        room_ids,
        matrix_user_id,
    )
    return {row["room_id"]: row["unread"] for row in rows}


async def get_room_members_display(
    pool: asyncpg.Pool,
    room_id: str,
    exclude_patterns: list[str] | None = None,
) -> list[dict]:
    """Get display names of room members (for DM name fallback).

    Excludes bot users and @conn-* users by default.
    """
    if exclude_patterns is None:
        exclude_patterns = ["@conn-%", "%bot:%"]

    query = """
        SELECT rm.user_id,
               COALESCE(
                   (SELECT ej.json::json->'content'->>'displayname'
                    FROM events e
                    JOIN event_json ej ON ej.event_id = e.event_id
                    WHERE e.room_id = rm.room_id
                      AND e.type = 'm.room.member'
                      AND e.state_key = rm.user_id
                    ORDER BY e.origin_server_ts DESC
                    LIMIT 1),
                   rm.user_id
               ) AS display_name
        FROM room_memberships rm
        WHERE rm.room_id = $1
          AND rm.membership = 'join'
    """
    # Add exclusion clauses
    params: list = [room_id]
    for i, pattern in enumerate(exclude_patterns, start=2):
        query += f"  AND rm.user_id NOT LIKE ${i}\n"
        params.append(pattern)

    rows = await pool.fetch(query, *params)
    return [{"user_id": r["user_id"], "display_name": r["display_name"]} for r in rows]


async def get_dm_avatar_urls(
    pool: asyncpg.Pool,
    room_ids: list[str],
    exclude_user_ids: list[str],
) -> dict[str, str]:
    """For small rooms (DM/bot), get the contact's avatar_url from member state.

    Returns {room_id: mxc_avatar_url}.
    Picks the first non-excluded member's avatar.
    """
    if not room_ids:
        return {}

    # Build exclusion: the user themselves + @conn-* patterns
    exclude_clause = ""
    params: list = [room_ids]
    idx = 2
    for uid in exclude_user_ids:
        exclude_clause += f" AND e.state_key != ${idx}"
        params.append(uid)
        idx += 1
    # Also exclude @conn-* puppets
    exclude_clause += f" AND e.state_key NOT LIKE ${idx}"
    params.append("@conn-%")

    rows = await pool.fetch(
        f"""
        SELECT DISTINCT ON (e.room_id)
            e.room_id,
            ej.json::json->'content'->>'avatar_url' AS avatar_url
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = ANY($1)
          AND e.type = 'm.room.member'
          AND ej.json::json->'content'->>'membership' = 'join'
          AND ej.json::json->'content'->>'avatar_url' IS NOT NULL
          AND ej.json::json->'content'->>'avatar_url' != ''
          {exclude_clause}
        ORDER BY e.room_id, e.origin_server_ts DESC
        """,
        *params,
    )
    return {r["room_id"]: r["avatar_url"] for r in rows}


async def get_room_messages(
    pool: asyncpg.Pool,
    room_id: str,
    limit: int = 50,
    before_stream_ordering: int | None = None,
    after_stream_ordering: int | None = None,
) -> tuple[list[dict], int | None, int | None]:
    """Paginated messages from events + event_json.

    - before: load older messages (stream_ordering < N, ORDER BY DESC)
    - after: poll for newer messages (stream_ordering > N, ORDER BY ASC)
    - neither: load latest N messages (ORDER BY DESC)

    Returns (messages_list, min_stream_ordering, max_stream_ordering).
    """
    params: list = [room_id]
    idx = 2

    where_extra = ""
    if before_stream_ordering is not None:
        where_extra += f" AND e.stream_ordering < ${idx}"
        params.append(before_stream_ordering)
        idx += 1
    if after_stream_ordering is not None:
        where_extra += f" AND e.stream_ordering > ${idx}"
        params.append(after_stream_ordering)
        idx += 1

    # For "after" queries, order ASC to get oldest-first new messages
    # For "before" or initial, order DESC to get newest-first
    if after_stream_ordering is not None:
        order = "ASC"
    else:
        order = "DESC"

    params.append(limit)
    limit_idx = idx

    rows = await pool.fetch(
        f"""
        SELECT
            e.event_id,
            e.sender,
            e.origin_server_ts AS timestamp,
            e.stream_ordering,
            ej.json::json->'content'->>'msgtype' AS msgtype,
            ej.json::json->'content'->>'body' AS body,
            ej.json::json->'content'->>'url' AS media_url,
            ej.json::json->'content'->'info'->>'thumbnail_url' AS thumbnail_url,
            ej.json::json->'content'->>'filename' AS file_name,
            ej.json::json->'content'->'info'->>'size' AS file_size,
            ej.json::json->'content'->'m.relates_to'->'m.in_reply_to'->>'event_id' AS reply_to_event_id
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = $1
          AND e.type = 'm.room.message'
          AND e.outlier = false
          AND NOT EXISTS (SELECT 1 FROM redactions r WHERE r.redacts = e.event_id)
          {where_extra}
        ORDER BY e.stream_ordering {order}
        LIMIT ${limit_idx}
        """,
        *params,
    )

    messages = []
    for row in rows:
        file_size = None
        if row["file_size"]:
            try:
                file_size = int(row["file_size"])
            except (ValueError, TypeError):
                pass

        messages.append({
            "event_id": row["event_id"],
            "sender": row["sender"],
            "timestamp": row["timestamp"],
            "stream_ordering": row["stream_ordering"],
            "msgtype": row["msgtype"] or "m.text",
            "body": row["body"] or "",
            "media_url": row["media_url"],
            "thumbnail_url": row["thumbnail_url"],
            "file_name": row["file_name"],
            "file_size": file_size,
            "reply_to_event_id": row["reply_to_event_id"],
        })

    # For DESC queries, reverse so messages are chronological (oldest first)
    if order == "DESC":
        messages.reverse()

    if not messages:
        return messages, None, None

    min_stream = min(m["stream_ordering"] for m in messages)
    max_stream = max(m["stream_ordering"] for m in messages)
    return messages, min_stream, max_stream


async def get_sender_profiles(
    pool: asyncpg.Pool,
    room_id: str,
    sender_ids: list[str],
) -> dict[str, dict]:
    """Batch display names + avatars from m.room.member state events.

    Returns {user_id: {display_name, avatar_url}}.
    """
    if not sender_ids:
        return {}

    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (e.state_key)
            e.state_key AS user_id,
            ej.json::json->'content'->>'displayname' AS display_name,
            ej.json::json->'content'->>'avatar_url' AS avatar_url
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = $1
          AND e.type = 'm.room.member'
          AND e.state_key = ANY($2)
        ORDER BY e.state_key, e.origin_server_ts DESC
        """,
        room_id,
        sender_ids,
    )

    return {
        row["user_id"]: {
            "display_name": row["display_name"] or row["user_id"],
            "avatar_url": row["avatar_url"],
        }
        for row in rows
    }


async def get_reactions_for_messages(
    pool: asyncpg.Pool,
    room_id: str,
    event_ids: list[str],
) -> dict[str, list[dict]]:
    """Fetch m.reaction events grouped by target event_id.

    Returns {event_id: [{key: "👍", count: 2, senders: ["@a:s", "@b:s"]}, ...]}.
    """
    if not event_ids:
        return {}

    rows = await pool.fetch(
        """
        SELECT
            ej.json::json->'content'->'m.relates_to'->>'event_id' AS relates_to,
            ej.json::json->'content'->'m.relates_to'->>'key' AS reaction_key,
            e.sender
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = $1
          AND e.type = 'm.reaction'
          AND e.outlier = false
          AND ej.json::json->'content'->'m.relates_to'->>'rel_type' = 'm.annotation'
          AND ej.json::json->'content'->'m.relates_to'->>'event_id' = ANY($2)
          AND NOT EXISTS (SELECT 1 FROM redactions r WHERE r.redacts = e.event_id)
        """,
        room_id,
        event_ids,
    )

    # Group by target event_id → key → senders
    from collections import defaultdict

    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        relates_to = row["relates_to"]
        key = row["reaction_key"]
        sender = row["sender"]
        if relates_to and key:
            grouped[relates_to][key].append(sender)

    # Convert to list of {key, count, senders}
    result: dict[str, list[dict]] = {}
    for event_id, key_map in grouped.items():
        result[event_id] = [
            {"key": k, "count": len(senders), "senders": senders}
            for k, senders in key_map.items()
        ]
    return result


async def get_edits_for_messages(
    pool: asyncpg.Pool,
    room_id: str,
    event_ids: list[str],
) -> dict[str, dict]:
    """Find the latest m.replace edit for each event_id.

    Returns {event_id: {edited_body: str, edit_ts: int}}.
    """
    if not event_ids:
        return {}

    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (ej.json::json->'content'->'m.relates_to'->>'event_id')
            ej.json::json->'content'->'m.relates_to'->>'event_id' AS relates_to,
            ej.json::json->'content'->'m.new_content'->>'body' AS edited_body,
            e.origin_server_ts AS edit_ts
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = $1
          AND e.type = 'm.room.message'
          AND e.outlier = false
          AND ej.json::json->'content'->'m.relates_to'->>'rel_type' = 'm.replace'
          AND ej.json::json->'content'->'m.relates_to'->>'event_id' = ANY($2)
          AND NOT EXISTS (SELECT 1 FROM redactions r WHERE r.redacts = e.event_id)
        ORDER BY ej.json::json->'content'->'m.relates_to'->>'event_id', e.origin_server_ts DESC
        """,
        room_id,
        event_ids,
    )

    result: dict[str, dict] = {}
    for row in rows:
        relates_to = row["relates_to"]
        if relates_to:
            result[relates_to] = {
                "edited_body": row["edited_body"] or "",
                "edit_ts": row["edit_ts"],
            }
    return result


async def get_new_events(
    pool: asyncpg.Pool,
    room_id: str,
    since_stream_ordering: int,
    limit: int = 100,
) -> list[dict]:
    """New m.room.message events after given stream_ordering.

    Returns messages in ASC order (oldest first) with full content.
    Excludes redacted messages and edit events (m.replace).
    """
    rows = await pool.fetch(
        """
        SELECT
            e.event_id,
            e.sender,
            e.origin_server_ts AS timestamp,
            e.stream_ordering,
            ej.json::json->'content'->>'msgtype' AS msgtype,
            ej.json::json->'content'->>'body' AS body,
            ej.json::json->'content'->>'url' AS media_url,
            ej.json::json->'content'->'info'->>'thumbnail_url' AS thumbnail_url,
            ej.json::json->'content'->>'filename' AS file_name,
            ej.json::json->'content'->'info'->>'size' AS file_size,
            ej.json::json->'content'->'m.relates_to'->'m.in_reply_to'->>'event_id' AS reply_to_event_id
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = $1
          AND e.stream_ordering > $2
          AND e.type = 'm.room.message'
          AND e.outlier = false
          AND NOT EXISTS (SELECT 1 FROM redactions r WHERE r.redacts = e.event_id)
          AND (ej.json::json->'content'->'m.relates_to'->>'rel_type' IS NULL
               OR ej.json::json->'content'->'m.relates_to'->>'rel_type' != 'm.replace')
        ORDER BY e.stream_ordering ASC
        LIMIT $3
        """,
        room_id,
        since_stream_ordering,
        limit,
    )

    messages = []
    for row in rows:
        file_size = None
        if row["file_size"]:
            try:
                file_size = int(row["file_size"])
            except (ValueError, TypeError):
                pass

        messages.append({
            "event_id": row["event_id"],
            "sender": row["sender"],
            "timestamp": row["timestamp"],
            "stream_ordering": row["stream_ordering"],
            "msgtype": row["msgtype"] or "m.text",
            "body": row["body"] or "",
            "media_url": row["media_url"],
            "thumbnail_url": row["thumbnail_url"],
            "file_name": row["file_name"],
            "file_size": file_size,
            "reply_to_event_id": row["reply_to_event_id"],
        })
    return messages


async def get_new_reactions(
    pool: asyncpg.Pool,
    room_id: str,
    since_stream_ordering: int,
) -> list[dict]:
    """New m.reaction events after given stream_ordering.

    Returns: [{event_id, target_event_id, key, sender, stream_ordering}]
    """
    rows = await pool.fetch(
        """
        SELECT
            e.event_id,
            e.sender,
            e.stream_ordering,
            ej.json::json->'content'->'m.relates_to'->>'event_id' AS target_event_id,
            ej.json::json->'content'->'m.relates_to'->>'key' AS reaction_key
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = $1
          AND e.stream_ordering > $2
          AND e.type = 'm.reaction'
          AND e.outlier = false
          AND ej.json::json->'content'->'m.relates_to'->>'rel_type' = 'm.annotation'
          AND NOT EXISTS (SELECT 1 FROM redactions r WHERE r.redacts = e.event_id)
        ORDER BY e.stream_ordering ASC
        """,
        room_id,
        since_stream_ordering,
    )

    return [
        {
            "event_id": row["event_id"],
            "target_event_id": row["target_event_id"],
            "key": row["reaction_key"],
            "sender": row["sender"],
            "stream_ordering": row["stream_ordering"],
        }
        for row in rows
        if row["target_event_id"] and row["reaction_key"]
    ]


async def get_new_edits(
    pool: asyncpg.Pool,
    room_id: str,
    since_stream_ordering: int,
) -> list[dict]:
    """New m.room.message events with rel_type=m.replace after given stream_ordering.

    Returns: [{target_event_id, edited_body, edit_ts, stream_ordering}]
    """
    rows = await pool.fetch(
        """
        SELECT
            e.stream_ordering,
            e.origin_server_ts AS edit_ts,
            ej.json::json->'content'->'m.relates_to'->>'event_id' AS target_event_id,
            ej.json::json->'content'->'m.new_content'->>'body' AS edited_body
        FROM events e
        JOIN event_json ej ON ej.event_id = e.event_id
        WHERE e.room_id = $1
          AND e.stream_ordering > $2
          AND e.type = 'm.room.message'
          AND e.outlier = false
          AND ej.json::json->'content'->'m.relates_to'->>'rel_type' = 'm.replace'
          AND NOT EXISTS (SELECT 1 FROM redactions r WHERE r.redacts = e.event_id)
        ORDER BY e.stream_ordering ASC
        """,
        room_id,
        since_stream_ordering,
    )

    return [
        {
            "target_event_id": row["target_event_id"],
            "edited_body": row["edited_body"] or "",
            "edit_ts": row["edit_ts"],
            "stream_ordering": row["stream_ordering"],
        }
        for row in rows
        if row["target_event_id"]
    ]


async def get_new_redactions(
    pool: asyncpg.Pool,
    room_id: str,
    since_stream_ordering: int,
) -> list[dict]:
    """New redaction events after given stream_ordering.

    Detects whether the redacted event was a message or a reaction.
    For reactions: also returns target_event_id, key, and sender so the
    frontend can remove the specific reaction from the message.

    Returns: [{redacted_event_id, stream_ordering, type,
               target_event_id?, key?, sender?}]
    """
    rows = await pool.fetch(
        """
        WITH new_redactions AS (
            SELECT
                e.stream_ordering,
                e.event_id AS redaction_event_id,
                COALESCE(
                    (SELECT r.redacts FROM redactions r
                     WHERE r.event_id = e.event_id LIMIT 1),
                    ej.json::json->'content'->>'redacts'
                ) AS redacted_event_id
            FROM events e
            JOIN event_json ej ON ej.event_id = e.event_id
            WHERE e.room_id = $1
              AND e.stream_ordering > $2
              AND e.type = 'm.room.redaction'
              AND e.outlier = false
        )
        SELECT
            nr.stream_ordering,
            nr.redacted_event_id,
            re.type AS redacted_event_type,
            re.sender AS redacted_sender,
            CASE WHEN re.type = 'm.reaction' THEN
                rej.json::json->'content'->'m.relates_to'->>'event_id'
            END AS reaction_target_event_id,
            CASE WHEN re.type = 'm.reaction' THEN
                rej.json::json->'content'->'m.relates_to'->>'key'
            END AS reaction_key
        FROM new_redactions nr
        LEFT JOIN events re ON re.event_id = nr.redacted_event_id
        LEFT JOIN event_json rej
            ON rej.event_id = nr.redacted_event_id
            AND re.type = 'm.reaction'
        WHERE nr.redacted_event_id IS NOT NULL
        ORDER BY nr.stream_ordering ASC
        """,
        room_id,
        since_stream_ordering,
    )

    results = []
    for row in rows:
        item: dict = {
            "redacted_event_id": row["redacted_event_id"],
            "stream_ordering": row["stream_ordering"],
        }
        if row["redacted_event_type"] == "m.reaction":
            item["type"] = "reaction"
            item["target_event_id"] = row["reaction_target_event_id"]
            item["key"] = row["reaction_key"]
            item["sender"] = row["redacted_sender"]
        else:
            item["type"] = "message"
        results.append(item)
    return results


async def get_room_invites(
    pool: asyncpg.Pool,
    matrix_user_id: str,
) -> list[str]:
    """Room IDs where user has membership='invite' (for auto-join)."""
    rows = await pool.fetch(
        """
        SELECT room_id
        FROM local_current_membership
        WHERE user_id = $1
          AND membership = 'invite'
        """,
        matrix_user_id,
    )
    return [r["room_id"] for r in rows]
