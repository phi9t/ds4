#!/usr/bin/env python3
"""Restore and run the current DS4 Colab rootfs without rebuilding remotely."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
import zipfile

from restore_layers import restore

RUN_NAME_PATTERN = re.compile(r'[a-z0-9-]+')
MODES = ('cpu', 'gpu')
APPS = ('ds4', 'ds4-bench', 'ds4-server', 'ds4-eval', 'ds4-agent')


def read_current_run_config(environ=os.environ):
    run_name = environ.get('DS4_CURRENT_COLAB_RUN', environ.get('DS4_ROOTFS_TEST_RUN', 'current'))
    if not RUN_NAME_PATTERN.fullmatch(run_name):
        raise ValueError('Invalid run name')
    mode = environ.get('DS4_CURRENT_COLAB_MODE', 'cpu')
    if mode == 'run':
        mode = 'cpu'
    if mode not in MODES:
        raise ValueError('Invalid current Colab mode')
    return run_name, mode


def driver_at_least(version, floor):
    def parse(value):
        return tuple(int(part) for part in re.findall(r'\d+', value)[:3])
    left = parse(version)
    right = parse(floor)
    return left >= right


class EvidenceRun:
    def __init__(self, run_name, mode):
        self.run_name = run_name
        self.mode = mode
        self.suffix = '-' + run_name
        self.base = Path('/content/current-evidence' + self.suffix)
        self.base.mkdir()
        self.status_path = Path('/content/current-status' + self.suffix + '.json')
        self.release = json.loads(Path('/content/release.json').read_text())
        self.records = []
        self.restore_result = None

    def status(self, phase, detail=None):
        temporary = self.status_path.with_suffix('.tmp')
        temporary.write_text(json.dumps({
            'phase': phase,
            'mode': self.mode,
            'detail': detail,
            'records': self.records,
            'restore': self.restore_result,
        }, indent=2))
        temporary.replace(self.status_path)

    def image(self):
        try:
            return self.release['images']['current']
        except KeyError as exc:
            raise ValueError('release.json is missing images.current') from exc

    def restore(self):
        cache = Path('/content/current-cache' + self.suffix)
        cache.mkdir()
        root = Path('/content/current-root' + self.suffix)
        self.restore_result = restore(
            self.image(),
            cache,
            root,
            '/content/crane',
            self.base / 'restore-current',
            lambda phase, detail: self.status('restore/' + phase, detail),
        )
        self.status('restore/materialized')
        shutil.rmtree('/content/ghcr-auth', ignore_errors=True)
        return root

    def run(self, name, root, args, *, expected=0, timeout=900, gpu=False):
        self.status(name)
        logs = self.base / name
        logs.mkdir()
        work = Path('/content/current-work' + self.suffix) / name
        weights = Path('/content/weights')
        weights.mkdir(exist_ok=True)
        command = [
            sys.executable,
            '/content/launch_insula.py',
            '--rootfs',
            str(root),
            '--work',
            str(work),
            '--weights',
            str(weights),
            '--outputs',
            str(logs),
            '--expected-bundle-sha256',
            self.image()['bundle_manifest_sha256'],
        ]
        if gpu:
            command.append('--gpu')
        command += ['--', *args]
        before = time.monotonic()
        with (logs / 'stdout.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        self.records.append({
            'name': name,
            'seconds': time.monotonic() - before,
            'returncode': result.returncode,
            'expected_returncode': expected,
            'gpu': gpu,
        })
        if result.returncode != expected:
            raise RuntimeError(name + ' failed')
        return logs

    def finish(self, success):
        with zipfile.ZipFile('/content/current-results' + self.suffix + '.zip',
                             'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.status_path, 'status.json')
            for path in self.base.rglob('*'):
                if path.is_file() and path.suffix in ('.log', '.json'):
                    archive.write(path, path.relative_to(self.base))
        return 0 if success else 1


def assert_cpu_or_gpu_mode(mode):
    has_gpu = Path('/dev/nvidia0').exists()
    if mode == 'cpu' and has_gpu:
        raise AssertionError('CPU admission requires a CPU-only Colab session')
    if mode == 'gpu' and not has_gpu:
        raise AssertionError('GPU mode requires an NVIDIA Colab runtime')


def check_rootfs(root):
    required = [
        'usr/bin/bwrap',
        'opt/ds4/bin/ds4',
        'opt/ds4/bundle-manifest.json',
        'opt/ds4/binaries.sha256',
    ]
    for item in required:
        if not (root / item).exists():
            raise FileNotFoundError(root / item)
    if not any((root / 'usr/local').glob('cuda-*/bin/nvcc')):
        raise FileNotFoundError(root / 'usr/local/cuda-*/bin/nvcc')


def run_common_checks(run, root, use_gpu):
    for app in APPS:
        run.run('help-' + app, root, ['/opt/ds4/bin/' + app, '--help'], gpu=use_gpu)
    expected_arch = run.release['candidate']['bundle_manifest']['cuda_arch']
    for app in ('ds4', 'ds4-server'):
        logs = run.run('build-id-' + app, root, ['/opt/ds4/bin/' + app, '--build-id'], gpu=use_gpu)
        text = (logs / 'stdout.log').read_text()
        if 'backend=cuda' not in text or f'arch={expected_arch}' not in text:
            raise AssertionError(app + ' build id mismatch: ' + text)
    run.run('toolchain-nvcc-version', root, ['/usr/local/cuda/bin/nvcc', '--version'], gpu=use_gpu)
    run.run(
        'readonly-root',
        root,
        [
            '/usr/bin/python3',
            '-c',
            "import errno; from pathlib import Path; exec(\"try:\\n"
            " Path('/opt/ds4/write-probe').write_text('x')\\n"
            "except OSError as e:\\n assert e.errno==errno.EROFS\\n"
            "else:\\n raise AssertionError('rootfs writable')\")",
        ],
        gpu=use_gpu,
    )


def run_gpu_checks(run, root):
    host_smi = subprocess.check_output(
        ['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
        text=True,
    ).strip()
    floor = run.release['candidate']['bundle_manifest']['rootfs_contract'].get('DS4_DRIVER_FLOOR', '0')
    first = host_smi.splitlines()[0]
    name, driver = [part.strip() for part in first.split(',', 1)]
    if 'A100' not in name and os.environ.get('DS4_CURRENT_COLAB_ALLOW_NON_A100') != '1':
        raise AssertionError('GPU runtime is not an A100: ' + name)
    if not driver_at_least(driver, floor):
        raise AssertionError(f'GPU driver {driver} is below required floor {floor}')
    (run.base / 'host-nvidia-smi.json').write_text(json.dumps({
        'query': host_smi,
        'driver_floor': floor,
    }, indent=2))
    run.run('inside-nvidia-smi', root,
            ['/run/nvidia-driver/bin/nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
            gpu=True)
    model_name = os.environ.get('DS4_CURRENT_COLAB_MODEL', 'ds4flash.gguf')
    model = Path('/content/weights') / model_name
    if not model.exists():
        run.status('gpu-generation-skipped', {'missing_model': str(model)})
        return
    prompt = os.environ.get('DS4_CURRENT_COLAB_PROMPT', 'The capital of France is')
    tokens = os.environ.get('DS4_CURRENT_COLAB_TOKENS', '8')
    run.run('gpu-generate-smoke', root,
            ['/opt/ds4/bin/ds4', '--cuda', '-m', '/weights/' + model_name,
             '-n', tokens, '--temp', '0', '-p', prompt],
            timeout=1800,
            gpu=True)


def main():
    run_name, mode = read_current_run_config()
    run = EvidenceRun(run_name, mode)
    success = False
    try:
        assert_cpu_or_gpu_mode(mode)
        root = run.restore()
        check_rootfs(root)
        use_gpu = mode == 'gpu'
        run_common_checks(run, root, use_gpu)
        if use_gpu:
            run_gpu_checks(run, root)
        success = True
        run.status('complete', {
            'mode': mode,
            'no_remote_rebuild': True,
            'reference': run.image()['reference'],
        })
    except BaseException:
        run.status('failed', {'error': traceback.format_exc(), 'mode': mode})
    finally:
        shutil.rmtree('/content/ghcr-auth', ignore_errors=True)
    return run.finish(success)


if __name__ == '__main__':
    raise SystemExit(main())
