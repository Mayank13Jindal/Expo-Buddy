import getpass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DBSession

from app.core.config import Settings
from app.core.security import hasher
from app.db.library import Owner, Session
from app.db.session import build_engine


def main() -> None:
    password = getpass.getpass("New password (at least 8 characters): ")
    if len(password) < 8 or len(password) > 256:
        raise SystemExit("Use 8–256 characters.")
    if getpass.getpass("Repeat new password: ") != password:
        raise SystemExit("Passwords do not match.")
    engine = build_engine(Settings())
    try:
        with DBSession(engine) as db:
            owner = db.scalar(select(Owner).with_for_update())
            if not owner:
                raise SystemExit("No account yet. Open the app to set up.")
            owner.password_hash = hasher.hash(password)
            owner.failed_logins = 0
            owner.locked_until = None
            db.execute(delete(Session))
            db.commit()
        print("Password reset. Sign in again on each device.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
