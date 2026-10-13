"""Acquire the exact Linux amd64 crane client used by the CPU benchmark."""
import argparse
import hashlib
from pathlib import Path
import tarfile
import tempfile
import urllib.request

URL = 'https://github.com/google/go-containerregistry/releases/download/v0.22.1/go-containerregistry_Linux_x86_64.tar.gz'
EXPECTED = '8e75c326adb43b053cfd78b9b987663f8f4fe4557f4d3915905643f25c730992'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('output must be a new file')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / 'release.tar.gz'
        with urllib.request.urlopen(URL, timeout=120) as response, archive.open('wb') as stream:
            import shutil
            shutil.copyfileobj(response, stream)
        with tarfile.open(archive) as release:
            member = release.getmember('crane')
            if not member.isfile():
                raise ValueError('crane release entry must be a regular file')
            with release.extractfile(member) as stream:
                binary = stream.read()
        if hashlib.sha256(binary).hexdigest() != EXPECTED:
            raise ValueError('crane binary differs from the benchmark pin')
        with args.output.open('xb') as stream:
            stream.write(binary)
        args.output.chmod(0o755)
    print(args.output)


if __name__ == '__main__':
    main()
