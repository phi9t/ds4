"""CPU-only restore and Insula execution evidence for Colab."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import traceback
import zipfile

from prepare_layers import write_layer
from restore_layers import restore


SOURCE_ARCHIVE_SHA256 = '1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3'
CRANE_SHA256 = '8e75c326adb43b053cfd78b9b987663f8f4fe4557f4d3915905643f25c730992'
RUN_NAME_PATTERN = re.compile(r'[a-z0-9-]+')
RUN_MODES = ('run', 'release-validation')
APPS = ('ds4', 'ds4-bench', 'ds4-server', 'ds4-eval', 'ds4-agent')


def read_run_config(environ=os.environ):
    run_name = environ.get('DS4_ROOTFS_TEST_RUN', 'final')
    if not RUN_NAME_PATTERN.fullmatch(run_name):
        raise ValueError('Invalid run name')
    mode = environ.get('DS4_ROOTFS_TEST_MODE', 'run')
    if mode == 'full':
        mode = 'release-validation'
    if mode not in RUN_MODES:
        raise ValueError('Invalid run mode')
    return run_name, mode


class EvidenceRun:
    def __init__(self, run_name, mode):
        self.run_name = run_name
        self.mode = mode
        self.suffix = '-' + run_name
        self.base = Path('/content/layered-evidence' + self.suffix)
        self.base.mkdir()
        self.status_path = Path('/content/layered-status' + self.suffix + '.json')
        self.release = json.loads(Path('/content/release.json').read_text())
        self.records = []
        self.restores = {}

    def status(self, phase, detail=None):
        temporary = self.status_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(
            phase=phase,
            mode=self.mode,
            detail=detail,
            records=self.records,
            restores=self.restores,
        ), indent=2))
        temporary.replace(self.status_path)

    def run(self, name, root, work, args, expected=0, timeout=1800):
        self.status(name)
        logs = self.base / name
        logs.mkdir()
        before = time.monotonic()
        with (logs / 'stdout.log').open('w') as log:
            result = subprocess.run(
                [
                    'python',
                    '/content/launch_insula.py',
                    '--rootfs',
                    str(root),
                    '--work',
                    str(work),
                    '--weights',
                    '/content/weights-empty',
                    '--outputs',
                    str(logs),
                    '--',
                    *args,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        self.records.append(dict(
            name=name,
            seconds=time.monotonic() - before,
            returncode=result.returncode,
            expected_returncode=expected,
        ))
        if result.returncode != expected:
            raise RuntimeError(name + ' failed')
        return logs

    def stage_image(self, name, cache):
        root = Path('/content/layered-root-' + name + self.suffix)
        result = restore(
            self.release['images'][name],
            cache,
            root,
            '/content/crane',
            self.base / ('restore-' + name),
            lambda phase, detail: self.status(name + '/' + phase, detail),
        )
        self.restores[name] = result
        self.status(name + '/restored')
        return root

    def finish(self, success):
        with zipfile.ZipFile(
            '/content/layered-results' + self.suffix + '.zip',
            'w',
            zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.write(self.status_path, 'status.json')
            for path in self.base.rglob('*'):
                if path.is_file() and path.suffix in ('.log', '.json'):
                    archive.write(path, path.relative_to(self.base))
        return 0 if success else 1


def assert_cpu_colab_and_crane():
    assert not Path('/dev/nvidia0').exists(), 'CPU-only session required'
    crane = Path('/content/crane')
    assert hashlib.sha256(crane.read_bytes()).hexdigest() == CRANE_SHA256
    crane.chmod(0o755)


def run_readonly_root_check(run, root, work):
    run.run(
        'readonly-root',
        root,
        work,
        [
            '/usr/bin/python3',
            '-c',
            "import errno; from pathlib import Path; exec(\"try:\\n"
            " Path('/opt/ds4/write-probe').write_text('x')\\n"
            "except OSError as e:\\n assert e.errno==errno.EROFS\\n"
            "else:\\n raise AssertionError('rootfs writable')\")",
        ],
    )


def run_packaged_apps(run, root, work, prefix):
    for app in APPS:
        run.run(prefix + '-' + app, root, work, ['/opt/ds4/bin/' + app, '--help'])


def run_prebuilt_payload(run):
    cache = Path('/content/layered-cache' + run.suffix)
    cache.mkdir()
    build = run.stage_image('build', cache)
    shutil.rmtree('/content/ghcr-auth')
    assert (build / 'usr/local/cuda-13.0/bin/nvcc').exists()
    assert (build / 'usr/bin/x86_64-linux-gnu-gcc-13').exists()
    assert (build / 'opt/ds4/source').is_dir()
    assert (build / 'opt/ds4/bin/ds4').is_file()
    work = Path('/content/build-run-work' + run.suffix)
    run_packaged_apps(run, build, work, 'build')
    run.run('toolchain-nvcc-version', build, work, ['/usr/local/cuda/bin/nvcc', '--version'])
    run.run('toolchain-gcc-version', build, work, ['/usr/bin/x86_64-linux-gnu-gcc-13', '--version'])
    run_readonly_root_check(run, build, work)


def run_release_validation(run):
    cache = Path('/content/layered-cache' + run.suffix)
    cache.mkdir()
    build = run.stage_image('build', cache)
    # Runtime gets its own empty cache for a genuine cold acquisition measurement.
    runtime = run.stage_image('runtime', Path('/content/layered-runtime-cold-cache' + run.suffix))
    # Seed shares previously acquired build blobs and downloads only the optional objects.
    seed = run.stage_image('seed', cache)
    shutil.rmtree('/content/ghcr-auth')
    assert not (runtime / 'usr/local/cuda-13.0/bin/nvcc').exists()
    assert not (runtime / 'usr/bin/x86_64-linux-gnu-gcc-13').exists()
    assert not (runtime / 'opt/ds4/source').exists()
    run_packaged_apps(run, runtime, Path('/content/runtime-work' + run.suffix), 'runtime')

    work = Path('/content/build-work' + run.suffix)
    work.mkdir()
    (work / 'probe.cu').write_text(
        '#include <cuda_runtime.h>\n__global__ void probe(int *p) { *p=42; }\n'
    )
    run.run(
        'compile-sm80',
        build,
        work,
        ['/usr/local/cuda/bin/nvcc', '-arch=sm_80', '-cubin', '/work/probe.cu', '-o', '/work/probe.cubin'],
    )
    logs = run.run(
        'inspect-sm80',
        build,
        work,
        ['/usr/local/cuda/bin/cuobjdump', '--dump-sass', '/work/probe.cubin'],
    )
    assert 'sm_80' in (logs / 'stdout.log').read_text()
    run_readonly_root_check(run, build, work)
    run.run(
        'copy-clean-source',
        build,
        work,
        ['/usr/bin/python3', '-c', "import shutil; shutil.copytree('/opt/ds4/source','/work/source')"],
    )
    assert not any((work / 'source').rglob('*.o'))
    run.run(
        'clean-cuda-build',
        build,
        work,
        [
            '/usr/bin/make',
            '-C',
            '/work/source',
            '-j2',
            'cuda',
            'CUDA_ARCH=sm_80',
            'NATIVE_CPU_FLAG=-march=x86-64',
        ],
        timeout=2400,
    )
    run.run('clean-rebuilt-help', build, work, ['/work/source/ds4-bench', '--help'])

    seeded = Path('/content/seed-work' + run.suffix)
    run.run('validate-object-seed', seed, seeded, ['/usr/bin/python3', '/opt/ds4/validate_object_seed.py'])
    logs = run.run(
        'refuse-mismatched-seed',
        seed,
        seeded,
        ['/usr/bin/python3', '/opt/ds4/validate_object_seed.py', '--cuda-arch', 'sm_100'],
        expected=2,
    )
    assert 'Object seed incompatible: cuda_arch' in (logs / 'stdout.log').read_text()
    run.run(
        'copy-seeded-source',
        seed,
        seeded,
        [
            '/usr/bin/python3',
            '-c',
            "import shutil; from pathlib import Path; "
            "shutil.copytree('/opt/ds4/source','/work/source'); "
            "Path('/work/source/ds4_bench.c').touch()",
        ],
    )
    logs = run.run(
        'seeded-incremental-build',
        seed,
        seeded,
        [
            '/usr/bin/make',
            '-C',
            '/work/source',
            '-j2',
            'ds4-bench',
            'CUDA_ARCH=sm_80',
            'NATIVE_CPU_FLAG=-march=x86-64',
        ],
    )
    commands = (logs / 'stdout.log').read_text()
    assert 'ds4_bench.c' in commands and '-c -o ds4_cuda.o' not in commands
    run.run('seeded-rebuilt-help', seed, seeded, ['/work/source/ds4-bench', '--help'])

    with (seeded / 'source/ds4_bench.c').open('a') as out:
        out.write('\nconst char ds4_layering_probe[] = "layering-reuse-20261011";\n')
    run.run(
        'edit-one-source-rebuild',
        seed,
        seeded,
        [
            '/usr/bin/make',
            '-C',
            '/work/source',
            '-j2',
            'ds4-bench',
            'CUDA_ARCH=sm_80',
            'NATIVE_CPU_FLAG=-march=x86-64',
        ],
    )
    run.run('edit-strip-binary', seed, seeded, ['/usr/bin/objcopy', '--strip-debug', '/work/source/ds4-bench', '/work/ds4-bench-edited'])
    run.run('edited-stripped-help', seed, seeded, ['/work/ds4-bench-edited', '--help'])

    # Re-compose the downloaded image from exact verified blobs, offline.
    packaging = work / 'packaging'
    shutil.copytree(build / 'opt/ds4/bazel/project', packaging)
    inputs = packaging / 'inputs'
    inputs.mkdir()
    names = {name: value['layer_names'] for name, value in run.release['images'].items()}
    for name, digest in zip(names['build'], [x['digest'] for x in run.release['images']['build']['layers']]):
        os.link(cache / digest, inputs / (name + '.tar.gz'))
    run.run(
        'offline-bazel-compose',
        build,
        work,
        ['/usr/bin/env', 'DS4_BAZEL_WORK_ROOT=/work/bazel-state', '/bin/sh', '/work/packaging/compose-offline.sh'],
    )

    def manifests(name):
        script = (
            "import hashlib,json; from pathlib import Path; result={};\n"
            "for name in ('runtime','build'):\n"
            " p=Path('/work/packaging/bazel-bin')/(name+'_image'); "
            "index=json.loads((p/'index.json').read_text()); "
            "digest=index['manifests'][0]['digest']; "
            "raw=(p/'blobs/sha256'/digest[7:]).read_bytes(); "
            "assert 'sha256:'+hashlib.sha256(raw).hexdigest()==digest; "
            "result[name]=dict(digest=digest,manifest=json.loads(raw))\n"
            "Path('/outputs/manifests.json').write_text(json.dumps(result,indent=2))"
        )
        logs = run.run(name, build, work, ['/usr/bin/python3', '-c', script])
        return json.loads((logs / 'manifests.json').read_text())

    baseline = manifests('offline-baseline-manifests')
    for name in ('runtime', 'build'):
        assert baseline[name]['digest'] == run.release['images'][name]['digest']

    # Pack the edited source and edited benchmark only. All other input blobs stay exact.
    probe = work / 'edit-root'
    (probe / 'opt/ds4').mkdir(parents=True)
    shutil.copytree(seeded / 'source', probe / 'opt/ds4/source')
    for path in (probe / 'opt/ds4/source').rglob('*.o'):
        path.unlink()
    for app in APPS:
        path = probe / 'opt/ds4/source' / app
        path.unlink()
        path.symlink_to('/opt/ds4/bin/' + app)
    paths = {str(p.relative_to(probe)) for p in probe.rglob('*')}
    source = inputs / 'source.tar.gz'
    source.unlink()
    write_layer(probe, paths, source)
    (probe / 'opt/ds4/bin').mkdir()
    shutil.copy2(seeded / 'ds4-bench-edited', probe / 'opt/ds4/bin/ds4-bench')
    app = inputs / 'app-ds4-bench.tar.gz'
    app.unlink()
    write_layer(probe, {'opt', 'opt/ds4', 'opt/ds4/bin', 'opt/ds4/bin/ds4-bench'}, app)
    meta = probe / 'opt/ds4'
    bundle = json.loads((build / 'opt/ds4/bundle-manifest.json').read_text())
    bundle['experiment_patch_sha256'] = hashlib.sha256((probe / 'opt/ds4/source/ds4_bench.c').read_bytes()).hexdigest()
    (meta / 'bundle-manifest.json').write_text(json.dumps(bundle, indent=2) + '\n')
    (meta / 'binaries.sha256').write_text(''.join(
        hashlib.sha256(
            (probe / 'opt/ds4/bin' / name if name == 'ds4-bench' else build / 'opt/ds4/bin' / name).read_bytes()
        ).hexdigest() + '  /opt/ds4/bin/' + name + '\n'
        for name in APPS
    ))
    shutil.copy2(build / 'opt/ds4/validate_object_seed.py', meta / 'validate_object_seed.py')
    metadata = inputs / 'metadata.tar.gz'
    metadata.unlink()
    write_layer(
        probe,
        {'opt', 'opt/ds4', 'opt/ds4/bundle-manifest.json', 'opt/ds4/binaries.sha256', 'opt/ds4/validate_object_seed.py'},
        metadata,
    )
    run.run(
        'offline-bazel-compose-edited',
        build,
        work,
        ['/usr/bin/env', 'DS4_BAZEL_WORK_ROOT=/work/bazel-state', '/bin/sh', '/work/packaging/compose-offline.sh'],
    )
    edited = manifests('offline-edited-manifests')
    for name, wanted in [('runtime', {'app-ds4-bench', 'metadata'}), ('build', {'source', 'app-ds4-bench', 'metadata'})]:
        old = baseline[name]['manifest']['layers']
        new = edited[name]['manifest']['layers']
        changed_names = {
            component
            for component, left, right in zip(names[name], old, new)
            if left['digest'] != right['digest']
        }
        assert changed_names == wanted, changed_names

    changed = {
        name: hashlib.sha256((inputs / (name + '.tar.gz')).read_bytes()).hexdigest()
        for name in names['build']
    }
    expected = dict(zip(names['build'], [x['digest'][7:] for x in run.release['images']['build']['layers']]))
    differences = [name for name, digest in changed.items() if digest != expected[name]]
    assert sorted(differences) == ['app-ds4-bench', 'metadata', 'source'], differences
    (run.base / 'changed-input-blobs.json').write_text(json.dumps(dict(
        changed=differences,
        unchanged=[name for name in names['build'] if name not in differences],
        new_sha256=changed,
    ), indent=2))


def main():
    run_name, mode = read_run_config()
    run = EvidenceRun(run_name, mode)
    success = False
    try:
        assert_cpu_colab_and_crane()
        if mode == 'run':
            run_prebuilt_payload(run)
        else:
            run_release_validation(run)
        success = True
        run.status('complete', dict(
            cpu_only=True,
            mode=mode,
            no_remote_rebuild=(mode == 'run'),
            source_archive_sha256=SOURCE_ARCHIVE_SHA256,
        ))
    except BaseException:
        run.status('failed', dict(error=traceback.format_exc(), mode=mode))
    finally:
        shutil.rmtree('/content/ghcr-auth', ignore_errors=True)
    return run.finish(success)


if __name__ == '__main__':
    raise SystemExit(main())
