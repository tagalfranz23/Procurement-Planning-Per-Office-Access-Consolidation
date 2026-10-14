"""Startup configuration regressions; no live database writes."""
import os
import unittest
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import app as application
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError


class StartupTests(unittest.TestCase):
    def test_environment_settings_include_port_and_escape_password(self):
        with patch.dict(os.environ, {
            'DB_BACKEND': 'mariadb', 'DB_HOST': 'db.example', 'DB_PORT': '3307', 'DB_NAME': 'procurement',
            'DB_USER': 'service', 'DB_PASSWORD': 'p@ss:/word',
        }, clear=True):
            url = make_url(application.database_uri())
        self.assertEqual((url.host, url.port, url.database, url.username, url.password),
                         ('db.example', 3307, 'procurement', 'service', 'p@ss:/word'))

    def test_database_url_takes_precedence(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'sqlite:///chosen.db', 'DB_PORT': 'invalid'}):
            self.assertEqual(application.database_uri(), 'sqlite:///chosen.db')

    def test_preflight_uses_application_engine(self):
        with application.app.app_context(), patch.object(application.db.engine, 'raw_connection') as connect:
            self.assertIs(application.get_db(), connect.return_value)
            connect.assert_called_once_with()

    def test_unavailable_database_gives_recovery_steps_without_migrating(self):
        error = OperationalError('connect', {}, Exception('Connection refused'))
        with patch.object(application, 'get_db', side_effect=error), \
                patch.object(application, 'migrate_revision_schema') as migrate:
            with self.assertRaisesRegex(RuntimeError, 'Unable to open the SQLite database'):
                application.initialize_database()
            migrate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
