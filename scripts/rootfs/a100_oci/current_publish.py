#!/usr/bin/env python3
"""Push a current DS4 Colab rootfs image to GHCR and write release.json."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

PROFILE = Path(__file__).resolve().parent
REPO_ROOT = PROFILE.parents[2]


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def output(command, **kwargs):
    return subprocess.check_output(command, text=True, **kwargs).strip()


def token_text(path):
    if path.stat().st_mode & 0o777 != 0o600:
        raise PermissionError('registry credential must have mode 0600')
    token = path.read_text().strip()
    if not token:
        raise ValueError('registry credential is empty')
    return token


def package_visibility(owner, package, token):
    request = urllib.request.Request(
        f'https://api.github.com/users/{owner}/packages/container/{package}',
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response).get('visibility')
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def acquire_crane(target):
    if target and target.is_file():
        return target
    destination = target or (Path(tempfile.gettempdir()) / 'ds4-crane')
    run(['python3', str(PROFILE / 'acquire_crane.py'), '--output', str(destination)])
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path,
                        default=REPO_ROOT / '.ds4/colab-current/latest-candidate.json')
    parser.add_argument('--owner', default='phi9t')
    parser.add_argument('--package', default='ds4-current-rootfs')
    parser.add_argument('--username', default=None,
                        help='GHCR username; default is --owner')
    parser.add_argument('--token-file', type=Path,
                        default=Path(os.environ.get('GHCR_TOKEN_FILE', Path.home() / '.config/ds4/secrets/ghcr-token')))
    parser.add_argument('--tag',
                        help='GHCR tag; default: main-<git>-<arch>')
    parser.add_argument('--crane', type=Path)
    parser.add_argument('--skip-private-check', action='store_true',
                        help='do not require the GHCR package to be private after push')
    args = parser.parse_args()

    raw_candidate = json.loads(args.candidate.read_text())
    if 'candidate' in raw_candidate and len(raw_candidate) == 1:
        candidate_path = Path(raw_candidate['candidate'])
        raw_candidate = json.loads(candidate_path.read_text())
    else:
        candidate_path = args.candidate
    local_image = raw_candidate.get('local_image')
    if not local_image:
        parser.error('candidate is missing local_image; run current_package.py without --no-import')
    token = token_text(args.token_file)
    username = args.username or args.owner
    repository = f'ghcr.io/{args.owner}/{args.package}'
    manifest = raw_candidate['bundle_manifest']
    tag = args.tag or f"main-{manifest['git_short']}-{manifest['cuda_arch']}"
    tag_ref = f'{repository}:{tag}'
    before_visibility = package_visibility(args.owner, args.package, token)
    if before_visibility not in (None, 'private') and not args.skip_private_check:
        raise ValueError(f'package {repository} is {before_visibility}, refusing to push')

    with tempfile.TemporaryDirectory(prefix='ds4-ghcr-push-') as temporary:
        docker_config = Path(temporary)
        auth_payload = {'auths': {'ghcr.io': {
            'auth': base64.b64encode(f'{username}:{token}'.encode()).decode()
        }}}
        (docker_config / 'config.json').write_text(json.dumps(auth_payload))
        (docker_config / 'config.json').chmod(0o600)
        env = dict(os.environ, DOCKER_CONFIG=str(docker_config))
        run(['docker', '--config', str(docker_config), 'tag', local_image, tag_ref])
        start = time.monotonic()
        run(['docker', '--config', str(docker_config), 'push', tag_ref])
        push_seconds = time.monotonic() - start
        crane = acquire_crane(args.crane or (candidate_path.parent / 'crane'))
        digest = output([str(crane), '--platform', 'linux/amd64', 'digest', tag_ref], env=env)
        reference = f'{repository}@{digest}'
        raw_manifest = subprocess.check_output(
            [str(crane), '--platform', 'linux/amd64', 'manifest', reference],
            env=env,
        )
    if 'sha256:' + hashlib.sha256(raw_manifest).hexdigest() != digest:
        raise ValueError('published manifest identity mismatch')
    remote_manifest = json.loads(raw_manifest)
    after_visibility = package_visibility(args.owner, args.package, token)
    if after_visibility != 'private' and not args.skip_private_check:
        raise ValueError(f'package {repository} visibility is {after_visibility!r}, expected private')

    image = {
        'name': 'current',
        'image': tag_ref,
        'reference': reference,
        'digest': digest,
        'layers': remote_manifest['layers'],
        'manifest': remote_manifest,
        'compressed_layer_bytes': sum(layer['size'] for layer in remote_manifest['layers']),
        'bundle_manifest_sha256': raw_candidate['bundle_manifest_sha256'],
        'push_seconds': push_seconds,
    }
    candidate = {
        'profile': raw_candidate['profile'],
        'local_image': raw_candidate.get('local_image'),
        'local_image_id': raw_candidate.get('local_image_id'),
        'bundle_manifest_sha256': raw_candidate['bundle_manifest_sha256'],
        'bundle_manifest': raw_candidate['bundle_manifest'],
    }
    release = {
        'schema_version': 2,
        'profile': 'current-bazel-rootfs',
        'package': repository,
        'visibility': after_visibility,
        'created_unix': int(time.time()),
        'candidate': candidate,
        'images': {'current': image},
    }
    release_path = candidate_path.parent / 'release.json'
    release_path.write_text(json.dumps(release, indent=2, sort_keys=True) + '\n')
    print(release_path)
    print(reference)


if __name__ == '__main__':
    main()
