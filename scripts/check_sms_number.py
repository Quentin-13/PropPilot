from memory.database import get_connection
with get_connection() as conn:
    row = conn.execute(
        "SELECT id, email, twilio_sms_number, plan_active FROM users WHERE email = %s",
        ("contact.maisondusommeil@gmail.com",),
    ).fetchone()
    print(dict(row) if row else "Non trouvé")
