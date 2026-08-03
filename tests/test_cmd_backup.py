"""Tests for `hevelius db backup` (hevelius.cli.basic.backup)."""

import tempfile
import unittest
from argparse import Namespace
from unittest.mock import MagicMock, patch

from hevelius.cli import basic


def _make_config(backup_path):
    return {
        'database': {
            'type': 'pgsql', 'user': 'u', 'password': 'p',
            'database': 'db', 'host': 'localhost', 'port': 5432,
        },
        'paths': {'backup-path': backup_path},
    }


class TestBackup(unittest.TestCase):
    def _run_backup(self, args, backup_path):
        def fake_popen(cmd, env=None):  # pylint: disable=unused-argument
            with open(cmd[-1], 'wb') as f:
                f.write(b'x' * 10)
            proc = MagicMock(communicate=MagicMock(return_value=(b'', b'')))
            proc.returncode = 0
            return proc

        with patch('hevelius.cli.basic.load_config', return_value=_make_config(backup_path)), \
             patch('hevelius.cli.basic.subprocess.Popen') as mock_popen, \
             patch('hevelius.cli.basic.subprocess.run') as mock_run:
            mock_popen.side_effect = fake_popen
            mock_run.return_value = MagicMock(stdout='pg_dump (PostgreSQL) 16.10\n')
            basic.backup(args)
        return mock_popen, mock_run

    def test_backup_without_skip_flags_excludes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(skip_tasks=False, skip_minor_planets=False, skip_projects=False)
            mock_popen, _ = self._run_backup(args, tmp)

            cmd = mock_popen.call_args[0][0]
            self.assertNotIn('--exclude-table-data', cmd)

    def test_skip_tasks_excludes_tasks_and_junction_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(skip_tasks=True, skip_minor_planets=False, skip_projects=False)
            mock_popen, _ = self._run_backup(args, tmp)

            cmd = mock_popen.call_args[0][0]
            excluded = {cmd[i + 1] for i, tok in enumerate(cmd) if tok == '--exclude-table-data'}
            self.assertEqual(excluded, {'tasks', 'task_projects'})

    def test_skip_projects_excludes_project_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(skip_tasks=False, skip_minor_planets=False, skip_projects=True)
            mock_popen, _ = self._run_backup(args, tmp)

            cmd = mock_popen.call_args[0][0]
            excluded = {cmd[i + 1] for i, tok in enumerate(cmd) if tok == '--exclude-table-data'}
            self.assertEqual(excluded, {'projects', 'project_subframes', 'project_users', 'task_projects'})

    def test_skip_minor_planets_excludes_asteroid_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(skip_tasks=False, skip_minor_planets=True, skip_projects=False)
            mock_popen, _ = self._run_backup(args, tmp)

            cmd = mock_popen.call_args[0][0]
            excluded = {cmd[i + 1] for i, tok in enumerate(cmd) if tok == '--exclude-table-data'}
            self.assertEqual(excluded, {'asteroids', 'asteroid_tag_map'})

    def test_all_skip_flags_dedupe_shared_junction_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(skip_tasks=True, skip_minor_planets=True, skip_projects=True)
            mock_popen, _ = self._run_backup(args, tmp)

            cmd = mock_popen.call_args[0][0]
            excluded = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == '--exclude-table-data']
            self.assertEqual(len(excluded), len(set(excluded)))
            self.assertEqual(
                set(excluded),
                {'tasks', 'projects', 'project_subframes', 'project_users', 'task_projects',
                 'asteroids', 'asteroid_tag_map'}
            )

    def test_prints_backup_path_size_and_pg_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(skip_tasks=False, skip_minor_planets=False, skip_projects=False)

            with patch('hevelius.cli.basic.load_config', return_value=_make_config(tmp)), \
                 patch('hevelius.cli.basic.subprocess.Popen') as mock_popen, \
                 patch('hevelius.cli.basic.subprocess.run') as mock_run, \
                 patch('builtins.print') as mock_print:

                def fake_popen(cmd, env=None):  # pylint: disable=unused-argument
                    full_path = cmd[-1]
                    with open(full_path, 'wb') as f:
                        f.write(b'x' * 2048)
                    proc = MagicMock(communicate=MagicMock(return_value=(b'', b'')))
                    proc.returncode = 0
                    return proc

                mock_popen.side_effect = fake_popen
                mock_run.return_value = MagicMock(stdout='pg_dump (PostgreSQL) 16.10\n')

                basic.backup(args)

            printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
            self.assertIn("Backup stored in", printed)
            self.assertIn("Backup size: 2.0 KiB", printed)
            self.assertIn("PostgreSQL version used to export: pg_dump (PostgreSQL) 16.10", printed)

    def test_failed_pg_dump_does_not_crash_or_report_a_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(skip_tasks=False, skip_minor_planets=False, skip_projects=False)

            with patch('hevelius.cli.basic.load_config', return_value=_make_config(tmp)), \
                 patch('hevelius.cli.basic.subprocess.Popen') as mock_popen, \
                 patch('hevelius.cli.basic.subprocess.run') as mock_run, \
                 patch('builtins.print') as mock_print:

                proc = MagicMock(communicate=MagicMock(return_value=(b'', b'connection failed')))
                proc.returncode = 1
                mock_popen.return_value = proc
                mock_run.return_value = MagicMock(stdout='pg_dump (PostgreSQL) 16.10\n')

                basic.backup(args)  # must not raise

            printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
            self.assertIn("pg_dump failed", printed)
            self.assertNotIn("Backup size", printed)


if __name__ == '__main__':
    unittest.main()
