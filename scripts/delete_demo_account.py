from memory.database import get_connection

DEMO_USER_ID = "demo-dumortier-gh-st-etienne"

with get_connection() as conn:
    print(f"Suppression du compte {DEMO_USER_ID}...\n")
    
    # 1. Conversations
    r = conn.execute(
        "DELETE FROM conversations WHERE client_id = %s",
        (DEMO_USER_ID,),
    )
    print(f"✓ Conversations supprimées : {r.rowcount}")
    
    # 2. Lead journey (référence les leads, doit partir AVANT)
    try:
        r = conn.execute(
            "DELETE FROM lead_journey WHERE lead_id IN (SELECT id FROM leads WHERE client_id = %s)",
            (DEMO_USER_ID,),
        )
        print(f"✓ Lead journey supprimé : {r.rowcount}")
    except Exception as e:
        print(f"  (lead_journey : {e})")
    
    # 3. Leads
    r = conn.execute(
        "DELETE FROM leads WHERE client_id = %s",
        (DEMO_USER_ID,),
    )
    print(f"✓ Leads supprimés : {r.rowcount}")
    
    # 4. Calls
    r = conn.execute(
        "DELETE FROM calls WHERE agency_id = %s OR client_id = %s",
        (DEMO_USER_ID, DEMO_USER_ID),
    )
    print(f"✓ Calls supprimés : {r.rowcount}")
    
    # 5. Usage tracking
    try:
        r = conn.execute(
            "DELETE FROM usage_tracking WHERE client_id = %s",
            (DEMO_USER_ID,),
        )
        print(f"✓ Usage tracking supprimé : {r.rowcount}")
    except Exception as e:
        print(f"  (usage_tracking : {e})")
    
    # 6. API actions
    try:
        r = conn.execute(
            "DELETE FROM api_actions WHERE client_id = %s",
            (DEMO_USER_ID,),
        )
        print(f"✓ API actions supprimées : {r.rowcount}")
    except Exception as e:
        print(f"  (api_actions : {e})")
    
    # 7. User
    r = conn.execute(
        "DELETE FROM users WHERE id = %s",
        (DEMO_USER_ID,),
    )
    print(f"✓ User supprimé : {r.rowcount}")
    
    conn.commit()
    
    # Vérif finale
    check = conn.execute(
        "SELECT id FROM users WHERE id = %s",
        (DEMO_USER_ID,),
    ).fetchone()
    print(f"\n{'✓ Compte bien supprimé' if check is None else '✗ Le compte existe encore'}")
