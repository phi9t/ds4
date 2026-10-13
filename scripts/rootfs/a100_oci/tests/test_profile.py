"""Portable checks for the experimental OCI profile; no GPU or registry access."""
import hashlib
import json
import stat
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

PROFILE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROFILE), str(PROFILE / 'layered')]
from pack_verified_layers import pack_image
from prepare_layers import write_layer
from cpu_layered_test import read_run_config
from current_colab_worker import driver_at_least, read_current_run_config


class ProfileTests(unittest.TestCase):
    def test_restore_command_is_relocatable(self):
        result = subprocess.run(
            [sys.executable, str(PROFILE / 'layered/restore_layers.py'), '--help'],
            capture_output=True, text=True, cwd='/tmp',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--release', result.stdout)

    def test_deterministic_layer_preserves_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'file').write_bytes(b'payload\n')
            (root / 'alias').symlink_to('file')
            import os
            os.link(root / 'file', root / 'hardlink')
            paths = {'file', 'alias', 'hardlink'}
            first = write_layer(root, paths, root / 'first.tar.gz')
            (root / 'file').touch()
            second = write_layer(root, paths, root / 'second.tar.gz')
            self.assertEqual(first['sha256'], second['sha256'])
            with tarfile.open(root / 'first.tar.gz') as archive:
                self.assertTrue(archive.getmember('alias').issym())
                self.assertTrue(archive.getmember('hardlink').islnk())
                self.assertEqual(archive.extractfile('file').read(), b'payload\n')

    def test_packing_keeps_compressed_bytes_and_refuses_bad_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blob = b'exact compressed bytes'
            digest = hashlib.sha256(blob).hexdigest()
            (root / ('sha256:' + digest)).write_bytes(blob)
            config = b'{}'
            manifest = {'config': {'size': len(config), 'digest': 'sha256:' + hashlib.sha256(config).hexdigest()},
                        'layers': [{'digest': 'sha256:' + digest, 'size': len(blob)}]}
            publication = {'reference': 'example.invalid/image@sha256:' + '0' * 64}
            output = root / 'image.tar'
            pack_image(publication, manifest, config, root, output)
            with tarfile.open(output) as archive:
                self.assertEqual(archive.extractfile(digest + '.tar.gz').read(), blob)
            with self.assertRaises((AssertionError, ValueError)):
                pack_image(publication, manifest, b'[]', root, output)

    def test_launcher_refuses_overlapping_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.run(
                [sys.executable, str(PROFILE / 'launch_insula.py'), '--rootfs', str(root),
                 '--work', str(root / 'work'), '--weights', str(root.parent / 'weights'),
                 '--outputs', str(root.parent / 'outputs'), '--', '/bin/true'],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn('must not overlap', result.stderr)

    def test_object_seed_refuses_architecture_and_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'opt/ds4').mkdir(parents=True)
            (root / 'source.o').write_bytes(b'compiled object')
            (root / 'Makefile').write_bytes(b'all:')
            sha = lambda name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            source_sha = '1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3'
            seed = {'source_archive_sha256': source_sha, 'cuda_arch': 'sm_80', 'cpu_flag': '-march=x86-64',
                    'compiler_files': {'Makefile': sha('Makefile')}, 'object_files': {'source.o': sha('source.o')}}
            (root / 'opt/ds4/object-seed.json').write_text(json.dumps(seed))
            (root / 'opt/ds4/bundle-manifest.json').write_text(json.dumps({'source_archive_sha256': source_sha}))
            command = [sys.executable, str(PROFILE / 'layered/validate_object_seed.py'), '--rootfs', str(root)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(command + ['--cuda-arch', 'sm_100'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            (root / 'source.o').write_bytes(b'corrupt')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)

    def test_make_colab_upload_bundle_is_flat_and_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            crane = root / 'crane'
            crane.write_bytes(b'test crane')
            output = root / 'ds4-colab-upload.tgz'
            result = subprocess.run(
                [sys.executable, str(PROFILE / 'make_colab_upload.py'),
                 '--output', str(output), '--crane', str(crane)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with tarfile.open(output) as archive:
                names = set(archive.getnames())
                expected = {
                    'README-COLAB.txt',
                    'crane',
                    'release.json',
                    'write_pull_auth.py',
                    'launch_insula.py',
                    'pack_verified_layers.py',
                    'start_cpu_worker.py',
                    'cpu_layered_test.py',
                    'restore_layers.py',
                    'prepare_layers.py',
                }
                self.assertTrue(expected <= names)
                self.assertFalse(any(name.startswith('layered/') for name in names))
                self.assertTrue(archive.getmember('crane').mode & 0o111)
                readme = archive.extractfile('README-COLAB.txt').read().decode()
                self.assertIn('DS4_ROOTFS_TEST_MODE', readme)
                self.assertIn('"run"', readme)

    def test_make_current_colab_upload_bundle_is_flat_and_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            crane = root / 'crane'
            crane.write_bytes(b'test crane')
            release = root / 'release.json'
            release.write_text(json.dumps({
                'schema_version': 2,
                'profile': 'current-bazel-rootfs',
                'candidate': {
                    'bundle_manifest': {
                        'cuda_arch': 'sm_80',
                    },
                },
                'images': {
                    'current': {
                        'reference': 'ghcr.io/phi9t/ds4-current-rootfs@sha256:' + 'a' * 64,
                        'bundle_manifest_sha256': 'b' * 64,
                        'layers': [{
                            'digest': 'sha256:' + 'c' * 64,
                            'size': 1,
                            'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip',
                        }],
                    },
                },
            }))
            output = root / 'ds4-current-colab-upload.tgz'
            result = subprocess.run(
                [sys.executable, str(PROFILE / 'make_current_colab_upload.py'),
                 '--release', str(release), '--output', str(output), '--crane', str(crane)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with tarfile.open(output) as archive:
                names = set(archive.getnames())
                expected = {
                    'README-COLAB.txt',
                    'crane',
                    'release.json',
                    'write_pull_auth.py',
                    'launch_insula.py',
                    'pack_verified_layers.py',
                    'start_current_worker.py',
                    'current_colab_worker.py',
                    'restore_layers.py',
                }
                self.assertTrue(expected <= names)
                self.assertFalse(any(name.startswith('layered/') for name in names))
                readme = archive.extractfile('README-COLAB.txt').read().decode()
                self.assertIn('DS4_CURRENT_COLAB_MODE', readme)
                self.assertIn('A100', readme)

    def test_cpu_worker_run_mode_is_the_default(self):
        self.assertEqual(read_run_config({'DS4_ROOTFS_TEST_RUN': 'r4'}), ('r4', 'run'))
        self.assertEqual(
            read_run_config({
                'DS4_ROOTFS_TEST_RUN': 'rv1',
                'DS4_ROOTFS_TEST_MODE': 'release-validation',
            }),
            ('rv1', 'release-validation'),
        )
        self.assertEqual(
            read_run_config({
                'DS4_ROOTFS_TEST_RUN': 'rv2',
                'DS4_ROOTFS_TEST_MODE': 'full',
            }),
            ('rv2', 'release-validation'),
        )
        with self.assertRaises(ValueError):
            read_run_config({'DS4_ROOTFS_TEST_RUN': 'bad/name'})
        with self.assertRaises(ValueError):
            read_run_config({'DS4_ROOTFS_TEST_RUN': 'r4', 'DS4_ROOTFS_TEST_MODE': 'rebuild'})

    def test_current_worker_mode_parsing_and_driver_floor(self):
        self.assertEqual(read_current_run_config({'DS4_CURRENT_COLAB_RUN': 'c1'}), ('c1', 'cpu'))
        self.assertEqual(
            read_current_run_config({
                'DS4_CURRENT_COLAB_RUN': 'g1',
                'DS4_CURRENT_COLAB_MODE': 'gpu',
            }),
            ('g1', 'gpu'),
        )
        self.assertEqual(
            read_current_run_config({
                'DS4_CURRENT_COLAB_RUN': 'c2',
                'DS4_CURRENT_COLAB_MODE': 'run',
            }),
            ('c2', 'cpu'),
        )
        with self.assertRaises(ValueError):
            read_current_run_config({'DS4_CURRENT_COLAB_RUN': 'bad/name'})
        with self.assertRaises(ValueError):
            read_current_run_config({'DS4_CURRENT_COLAB_RUN': 'c1', 'DS4_CURRENT_COLAB_MODE': 'rebuild'})
        self.assertTrue(driver_at_least('580.82.07', '580.0'))
        self.assertFalse(driver_at_least('570.99', '580.0'))

    def test_launcher_checks_current_bundle_hash_when_provided(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'opt/ds4').mkdir(parents=True)
            (root / 'opt/ds4/bundle-manifest.json').write_text(
                json.dumps({'profile': 'current-bazel-rootfs'}) + '\n'
            )
            result = subprocess.run(
                [sys.executable, str(PROFILE / 'launch_insula.py'),
                 '--rootfs', str(root),
                 '--work', str(root.parent / 'work'),
                 '--weights', str(root.parent / 'weights'),
                 '--outputs', str(root.parent / 'outputs'),
                 '--expected-bundle-sha256', '0' * 64,
                 '--', '/bin/true'],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn('bundle manifest differs', result.stderr)

    def test_write_pull_auth_uses_stdin_without_echoing_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'pull-auth.json'
            result = subprocess.run(
                [sys.executable, str(PROFILE / 'write_pull_auth.py'),
                 '--output', str(output), '--username', 'alice', '--token-stdin'],
                input='secret-token\n', capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('secret-token', result.stdout + result.stderr)
            payload = json.loads(output.read_text())
            encoded = payload['auths']['ghcr.io']['auth']
            self.assertEqual(encoded, 'YWxpY2U6c2VjcmV0LXRva2Vu')
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_provide_colab_auth_can_write_local_auth_without_colab(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'pull-auth.json'
            result = subprocess.run(
                [sys.executable, str(PROFILE / 'provide_colab_auth.py'),
                 '--local-output', str(output), '--username', 'alice',
                 '--token-stdin'],
                input='secret-token\n', capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('secret-token', result.stdout + result.stderr)
            payload = json.loads(output.read_text())
            self.assertEqual(payload['auths']['ghcr.io']['auth'],
                             'YWxpY2U6c2VjcmV0LXRva2Vu')
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)


if __name__ == '__main__':
    unittest.main()
