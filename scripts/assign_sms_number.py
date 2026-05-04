from memory.database import get_connection

USER_ID = "c15e31cf-341d-48be-8e7c-f5949b6dc1a6"
SMS_NUMBER = "+33757596114"

with get_connection() as conn:
    conn.execute(
        "UPDATE users SET twilio_sms_number = %s WHERE id = %s",
        (SMS_NUMBER, USER_ID),
    )
    conn.commit()
    
    row = conn.execute(
        "SELECT id, email, twilio_sms_number, plan_active FROM users WHERE id = %s",
        (USER_ID,),
    ).fetchone()
    print("Après update :", dict(row))
