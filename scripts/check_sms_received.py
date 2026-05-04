from memory.database import get_connection

with get_connection() as conn:
    rows = conn.execute(
        """
        SELECT c.id, c.lead_id, c.canal, c.role, c.contenu, c.created_at, l.telephone
        FROM conversations c
        LEFT JOIN leads l ON l.id = c.lead_id
        WHERE c.client_id = %s AND c.canal = 'sms'
        ORDER BY c.created_at DESC
        LIMIT 5
        """,
        ("c15e31cf-341d-48be-8e7c-f5949b6dc1a6",),
    ).fetchall()
    
    print(f"Derniers SMS reçus : {len(rows)}\n")
    for r in rows:
        print(f"[{r['created_at']}] {r['telephone']} ({r['role']})")
        print(f"  → {r['contenu'][:100]}")
        print(f"  Lead: {r['lead_id'][:8]}... | Conv: {r['id'][:8]}...\n")
