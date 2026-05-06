"""
scripts/create_admin.py — Crée le premier compte admin (bootstrap).

Usage :
    python -m scripts.create_admin

Demande interactivement username, full_name, email et mot de passe.
À utiliser UNIQUEMENT pour créer le tout premier admin, après quoi tous
les autres comptes peuvent être créés via POST /api/v1/auth/register.

Le mot de passe est saisi en mode masqué (getpass) — il n'apparaît pas
dans l'historique du shell ni à l'écran.
"""

import sys
import getpass
from pathlib import Path

# Ajouter la racine du projet au path pour les imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth.security import hash_password
from infrastructure.database.user_repository import UserRepository


def _prompt(label: str, default: str | None = None) -> str:
    """Lit une ligne, retourne default si vide."""
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix} : ").strip()
    return val or (default or "")


def _prompt_password() -> str:
    """Lit un mot de passe en double pour éviter les fautes de frappe."""
    while True:
        pwd1 = getpass.getpass("Mot de passe (min 8 car.) : ")
        if len(pwd1) < 8:
            print("⚠️  Trop court (8 caractères minimum). Recommencez.")
            continue
        pwd2 = getpass.getpass("Confirmer : ")
        if pwd1 != pwd2:
            print("⚠️  Les mots de passe ne correspondent pas. Recommencez.")
            continue
        return pwd1


def main() -> int:
    print("=" * 60)
    print("  Création du premier compte ADMIN — Text-to-SQL DGD")
    print("=" * 60)
    print()

    username = _prompt("Nom d'utilisateur (3-64 car., sans espace)")
    if not username or len(username) < 3:
        print("✗ Username invalide.")
        return 1

    full_name = _prompt("Nom complet (optionnel)") or None
    email = _prompt("Email (optionnel)") or None
    password = _prompt_password()

    repo = UserRepository()
    try:
        new_user = repo.create(
            username=username,
            password_hash=hash_password(password),
            email=email,
            full_name=full_name,
            role="admin",
        )
    except ValueError as ve:
        print(f"\n✗ Erreur : {ve}")
        return 1
    except Exception as exc:
        print(f"\n✗ Erreur BDD : {exc}")
        print("   Vérifiez que la migration 002_users.sql a bien été appliquée.")
        return 2

    print()
    print("✓ Admin créé avec succès !")
    print(f"  ID:       {new_user['id']}")
    print(f"  Username: {new_user['username']}")
    print(f"  Role:     {new_user['role']}")
    print()
    print("Vous pouvez maintenant vous connecter via POST /api/v1/auth/login")
    return 0


if __name__ == "__main__":
    sys.exit(main())