"""Password-free access keeps sessions and cross-site write protection."""
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.storage import MARKER
from app.db.library import Owner
from app.db.library import Session as LoginSession
from app.db.models import Base
from app.main import create_app


class PasswordlessTest(unittest.TestCase):
    def test_open_renew_and_cross_site_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = dict(app_url='https://localhost:8443', assets_free_floor_bytes=0, passwordless=True)
            for name in ('assets', 'previews', 'db', 'models', 'exports', 'backup'):
                folder = root / name
                folder.mkdir()
                volume_id = uuid4()
                (folder / MARKER).write_text(str(volume_id))
                values[f'{name}_dir'] = folder
                values[f'{name}_volume_id'] = volume_id
            for name, content in [('database_password', 'a' * 48), ('host_id', str(uuid4())), ('encryption_key', Fernet.generate_key().decode())]:
                file = root / name
                file.write_text(content)
                values[f'{name}_file'] = file
            settings = Settings(**values)
            engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
            Base.metadata.create_all(engine)
            with TestClient(create_app(settings, engine=engine), base_url='https://localhost:8443', headers={'Origin': 'https://localhost:8443'}) as client:
                self.assertFalse(client.get('/api/v1/auth/status').json()['password_required'])
                self.assertEqual(client.post('/api/v1/auth/open', headers={'Origin': 'https://wrong.example'}).status_code, 403)
                self.assertEqual(client.post('/api/v1/auth/open').status_code, 200)
                self.assertEqual(client.get('/api/v1/settings/providers').status_code, 200)
                self.assertEqual(client.get('/api/v1/accuracy').status_code, 200)
                self.assertEqual(client.post('/api/v1/expos', json={'name': 'Test'}).status_code, 403)
                client.headers['x-csrf-token'] = client.cookies['expo_csrf']
                self.assertEqual(client.post('/api/v1/expos', json={'name': 'Test'}).status_code, 201)
                self.assertEqual(client.post('/api/v1/expos', json={'name': 'Blocked'}, headers={'Origin': 'https://wrong.example'}).status_code, 403)
                with Session(engine) as db:
                    login = db.scalar(select(LoginSession))
                    login.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    db.commit()
                self.assertEqual(client.get('/api/v1/auth/me').status_code, 401)
                self.assertEqual(client.post('/api/v1/auth/open').status_code, 200)
                with Session(engine) as db:
                    self.assertEqual(db.scalar(select(func.count()).select_from(Owner)), 1)
                settings.passwordless = False
                self.assertEqual(client.post('/api/v1/auth/open').status_code, 403)
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
