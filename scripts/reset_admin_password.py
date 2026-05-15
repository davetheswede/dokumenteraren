from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import db  # noqa: E402
from app.config import DB_PATH  # noqa: E402


def read_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        value = sys.stdin.readline().rstrip("\n")
    elif args.password:
        value = args.password
    else:
        value = getpass.getpass("Nytt temporärt adminlösenord: ")
        confirm = getpass.getpass("Upprepa lösenord: ")
        if value != confirm:
            raise ValueError("Lösenorden matchar inte.")
    if len(value) < 8:
        raise ValueError("Adminlösenordet behöver vara minst 8 tecken.")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resetta adminkontots lösenord direkt i dokumenteraren-databasen."
    )
    parser.add_argument(
        "--password",
        help="Nytt temporärt lösenord. Undvik i shell-historik; använd helst prompt eller --password-stdin.",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Läs nytt temporärt lösenord från stdin.",
    )
    parser.add_argument(
        "--no-force-change",
        action="store_true",
        help="Kräv inte lösenordsbyte vid nästa adminlogin.",
    )
    args = parser.parse_args()

    if args.password and args.password_stdin:
        parser.error("Använd antingen --password eller --password-stdin, inte båda.")

    try:
        db.init_db()
        password = read_password(args)
        if not db.reset_admin_password(password, must_change_password=not args.no_force_change):
            print("Kunde inte hitta adminkontot.", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Adminreset misslyckades: {exc}", file=sys.stderr)
        return 1

    print(f"Adminlösenordet är reset i {DB_PATH}.")
    if not args.no_force_change:
        print("Admin måste byta lösenord vid nästa inloggning.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
