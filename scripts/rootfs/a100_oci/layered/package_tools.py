from pathlib import Path
import argparse
import os
import tarfile, gzip, hashlib, json
parser = argparse.ArgumentParser(description='Package a verified Bazel binary and offline vendor tree')
parser.add_argument('--tools', type=Path, required=True, help='Directory with bin/bazel, bazel.LICENSE and vendor/')
parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parent/'bazel')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
bundle = args.tools.resolve(strict=True)
project = args.project.resolve(strict=True)
expected = json.loads((project/'acquisition.json').read_text())['bazel']['sha256']
with (bundle/'bin/bazel').open('rb') as stream:
 if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
  raise ValueError('Bazel binary differs from acquisition pin')
files = ['MODULE.bazel', 'MODULE.bazel.lock', 'BUILD.bazel', 'compose-offline.sh', 'link-layers.sh', 'verify-layout.py', 'README.md', 'acquisition.json']
output = args.output
if output.exists(): raise ValueError('Output already exists')
output.parent.mkdir(parents=True, exist_ok=True)
with output.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=9) as gz, tarfile.open(fileobj=gz, mode='w|', format=tarfile.GNU_FORMAT) as tar:
 def add(src, dst):
  info=tar.gettarinfo(str(src),arcname=dst)
  info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=0
  if info.isdir():info.mode=0o755
  elif info.isfile():info.mode=0o755 if info.mode & 0o111 else 0o644
  if info.isfile():
   with src.open('rb') as f:tar.addfile(info,f)
  else:tar.addfile(info)
 add(bundle/'bin/bazel','opt/ds4/bin/bazel')
 add(bundle/'bazel.LICENSE','opt/ds4/bin/bazel.LICENSE')
 for name in files:add(project/name,'opt/ds4/bazel/project/'+name)
 root=bundle/'vendor'
 add(root,'opt/ds4/bazel/vendor')
 for source in sorted(root.rglob('*')):
  relative=source.relative_to(root)
  if relative.as_posix()=='bazel-external':continue
  if source.is_symlink():
   assert not source.readlink().is_absolute()
   assert source.resolve().is_relative_to(root)
  add(source,'opt/ds4/bazel/vendor/'+relative.as_posix())
h=hashlib.sha256()
with output.open('rb') as f:
 for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
receipt={'file':str(output),'bytes':output.stat().st_size,'sha256':h.hexdigest(),'excluded':['vendor/bazel-external','inputs','outputbase','repository-cache','fixtures'],'recipe_files':files}
output.with_suffix('.receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
