import importlib.util
import io
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location('audit', Path(__file__).parents[1] / 'scripts/audit_benchmark_sources.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class SourceAuditTests(unittest.TestCase):
    def archive(self, path, entries):
        with tarfile.open(path, 'w:gz') as tar:
            for name, data in entries:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

    def test_rejects_parent_and_git_paths(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'source.tar.gz'
            for bad in ('root/../outside', 'root/.git/config'):
                self.archive(p, [(bad, b'bad')])
                with self.assertRaises(ValueError):
                    audit.archive_entries(p)

    def test_exact_tree_and_repeatable_conflict(self):
        with tempfile.TemporaryDirectory() as d, patch.object(audit, 'CACHE', Path(d)):
            root = Path(d)
            repo = root / 'repo'; repo.mkdir()
            subprocess.run(['git', 'init', '-q', '--template=', str(repo)], check=True, env=audit.ENV)
            (repo / 'file').write_text('base\n')
            (repo / 'omitted').write_text('tracked\n')
            subprocess.run(['git', '-C', str(repo), 'add', 'file', 'omitted'], check=True, env=audit.ENV)
            tree = subprocess.check_output(['git', '-C', str(repo), 'write-tree'], env=audit.ENV).decode().strip()
            archive = root / 'source.tar.gz'
            self.archive(archive, [('root/file', b'base\n')])
            a = b'diff --git a/file b/file\n--- a/file\n+++ b/file\n@@ -1 +1 @@\n-base\n+one\n'
            b = a.replace(b'+one', b'+two')
            result = audit.replay(archive, tree, [a, b], [('omitted', '100644', b'tracked\n')])
            self.assertEqual((result['status'], result['label'], result['repeat_identical']), ('complete', 'conflict', True))
            self.assertEqual(audit.replay(archive, '0' * 40, [a, b])['status'], 'unverified_tree')


if __name__ == '__main__':
    unittest.main()
