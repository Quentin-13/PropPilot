"""Reset propre de la base de données."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.database import reset_database

if __name__ == "__main__":
    confirm = input("⚠️  Réinitialiser la base de données ? Toutes les données seront perdues. (oui/non) : ")
    if confirm.strip().lower() == "oui":
        reset_database()
        print("✅ Base de données réinitialisée.")
    else:
        print("Annulé.")
