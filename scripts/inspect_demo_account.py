from memory.database import get_connection

USER_ID = "demo-dumortier-gh-st-etienne"

with get_connection() as conn:
    user = conn.execute(
        "SELECT * FROM users WHERE id = %s",
        (USER_ID,),
    ).fetchone()
    print("=== USER ===")
    print(dict(user) if user else "Non trouvé")
    
    print("\n=== DONNÉES RATTACHÉES ===")
    
    for table, col in [
        ("leads", "client_id"),
        ("calls", "agency_id"),
        ("calls", "client_id"),
        ("conversations", "client_id"),
        ("agency_phone_numbers", "user_id"),
    ]:
        try:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {col} = %s",
                (USER_ID,),
            ).fetchone()
            print(f"{table}.{col} : {row['n']} lignes")
        except Exception as e:
            print(f"{table}.{col} : erreur ({e})")
