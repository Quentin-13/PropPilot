from memory.database import get_connection

with get_connection() as conn:
    rows = conn.execute(
        "SELECT id, email, twilio_sms_number, plan_active, created_at FROM users WHERE twilio_sms_number = %s",
        ("+33757596114",),
    ).fetchall()
    print(f"Users avec ce numéro SMS : {len(rows)}")
    for r in rows:
        print(dict(r))
