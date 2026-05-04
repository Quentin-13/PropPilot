from memory.database import get_connection

with get_connection() as conn:
    rows = conn.execute(
        """
        SELECT id, lead_id, role, contenu, created_at
        FROM conversations
        WHERE client_id = %s AND canal = 'sms'
        ORDER BY created_at DESC
        LIMIT 10
        """,
        ("c15e31cf-341d-48be-8e7c-f5949b6dc1a6",),
    ).fetchall()
    print(f"Total derniers SMS : {len(rows)}\n")
    for r in rows:
        print(f"[{r['created_at']}] role={r['role']}")
        print(f"  → {r['contenu'][:80]}")
