#!/usr/bin/env python3
"""Create a partner-role user (e.g. Tzvi) directly in the database.

Usage (from reddit_saas/ directory):
    python scripts/create_partner_user.py
    python scripts/create_partner_user.py --email tzvi@example.com --name "Tzvi Vaknin" --password "ChangeMe123!"

Connects to the DATABASE_URL in .env (or .env.production if --prod flag is passed).
Requires the schema to already exist (run `alembic upgrade head` first).
"""

import argparse
import sys
from pathlib import Path

# Add project root to path so app imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a partner-role user")
    parser.add_argument("--email", default="tzvi@ramp.co", help="User email")
    parser.add_argument("--name", default="Tzvi Vaknin", help="Full name")
    parser.add_argument("--password", required=True, help="Login password")
    parser.add_argument("--prod", action="store_true", help="Use .env.production instead of .env")
    args = parser.parse_args()

    # Load environment
    env_file = PROJECT_ROOT / (".env.production" if args.prod else ".env")
    if not env_file.exists():
        print(f"ERROR: {env_file} not found. Copy .env.example and fill in values.")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv(env_file)

    from app.database import SessionLocal
    from app.models.user import User
    from app.models.user_role import UserRole
    from app.services.auth import create_user

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == args.email).first()
        if existing:
            # Update role if user already exists
            existing.role = UserRole.partner.value
            existing.is_superuser = False  # partner doesn't need legacy superuser flag
            db.commit()
            print(f"User already exists — role updated to 'partner': {existing.email}")
        else:
            user = create_user(
                db,
                email=args.email,
                password=args.password,
                full_name=args.name,
            )
            user.role = UserRole.partner.value
            user.is_superuser = False
            user.client_id = None  # partner has no client scope
            db.commit()
            db.refresh(user)
            print(f"Created partner user:")
            print(f"  Email:    {user.email}")
            print(f"  Name:     {user.full_name}")
            print(f"  Role:     {user.role}")
            print(f"  ID:       {user.id}")
            print()
            print("Share with Tzvi:")
            print(f"  URL:      http://localhost:8000/login  (or production URL)")
            print(f"  Email:    {user.email}")
            print(f"  Password: {args.password}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
