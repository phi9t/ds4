"""Select immutable DS4 rootfs components and write deterministic gzip OCI layers."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time

RECIPE = Path(__file__).resolve().parent
HERE = Path(os.environ.get('DS4_ROOTFS_STATE', RECIPE))
ORIGINAL = Path(os.environ.get('DS4_ROOTFS_INPUTS', RECIPE.parent))
EXPECTED_SOURCE = '1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3'
IMAGE = os.environ.get('DS4_BUILDER_IMAGE', 'sha256:03a4d77a509f59a204747661ef7207232c846cb1146077073ef87116009d7462')
CUDA = 'usr/local/cuda-13.0/'
APPS = ('ds4','ds4-bench','ds4-server','ds4-eval','ds4-agent')
COMPILER_BINS = {'nvcc','nvcc.profile','ptxas','fatbinary','nvlink','cudafe++','cuobjdump','nvdisasm','bin2c','__nvcc_device_query','crt'}
CUDA_STATIC = {'libcudart_static.a','libcudadevrt.a','libculibos.a'}
COMPILER_NAMES = re.compile(r'^(?:(?:x86_64-linux-gnu-)?(?:gcc|g\+\+|cpp)(?:-\d+)?(?:-(?:ar|nm|ranlib)(?:-\d+)?)?|cc|c\+\+|c89-gcc|c99-gcc|make|gmake|ar|as|ld(?:\.bfd|\.gold)?|nm|objcopy|objdump|ranlib|readelf|size|strings|strip|addr2line|c\+\+filt|elfedit|gprof|gcov(?:-\d+)?|lto-dump(?:-\d+)?)$')


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source,'sha256').hexdigest()


def select(name, source_members):
    if name.startswith(('dev/','proc/','sys/','tmp/','opt/nvidia/')) or name in ('dev','proc','sys','tmp','.dockerenv'):
        return None
    if name in ('etc/hosts','etc/hostname','etc/resolv.conf'):
        return None
    if name in ('usr/local/bin/nsys','etc/cufile.json','etc/alternatives/cufile.json'):
        return None
    if name in ('etc/alternatives/cc','etc/alternatives/c++','etc/alternatives/cpp','etc/alternatives/c89','etc/alternatives/c99'):
        return 'compiler'
    if name.startswith('opt/ds4/source/'):
        relative=name[len('opt/ds4/source/'):]
        if relative in source_members:
            return 'source'
        return 'objects' if relative.endswith('.o') else None
    if name.startswith('opt/ds4/bin/'):
        return 'app' if name.rsplit('/',1)[1] in APPS else None
    if name.startswith('opt/ds4/'):
        return None
    if name.startswith(CUDA):
        relative=name[len(CUDA):]
        if relative in ('lib64','doc') or relative.startswith('doc/'):
            return 'cuda-runtime'
        if relative.startswith('targets/x86_64-linux/lib/'):
            base=relative.rsplit('/',1)[1]
            if base.startswith(('libcublas.so','libcublasLt.so','libcudart.so')):
                return 'cuda-runtime'
            if base in CUDA_STATIC or relative.startswith('targets/x86_64-linux/lib/stubs/'):
                return 'compiler'
            return None
        if relative in ('include','bin','nvvm','targets','targets/x86_64-linux','targets/x86_64-linux/include'):
            return 'compiler'
        if relative.startswith(('nvvm/','targets/x86_64-linux/include/')):
            return 'compiler'
        if relative.startswith('bin/') and relative.split('/')[1] in COMPILER_BINS:
            return 'compiler'
        return None
    if name.startswith('usr/local/cuda') or name.startswith('etc/alternatives/cuda'):
        return 'cuda-runtime'
    if name.startswith(('usr/lib/x86_64-linux-gnu/libnccl','usr/include/nccl')):
        return None
    if name.startswith(('usr/include/','usr/lib/gcc/','usr/libexec/')) or name.endswith('.a'):
        return 'compiler'
    if name.startswith('usr/bin/') and COMPILER_NAMES.fullmatch(name.rsplit('/',1)[1]):
        return 'compiler'
    return 'os'


def write_layer(root, paths, destination):
    begin=time.monotonic()
    # tarfile's inode tracking retains hardlinks within each component.
    with destination.open('wb') as target, gzip.GzipFile(fileobj=target,filename='',mode='wb',mtime=0,compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed,mode='w|',format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(paths):
                path=root/name
                info=archive.gettarinfo(str(path),arcname=name)
                info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
                info.pax_headers={}
                if not (info.isfile() or info.isdir() or info.issym() or info.islnk()):
                    raise ValueError('Unsupported rootfs entry: '+name)
                if info.isfile():
                    with path.open('rb') as source:archive.addfile(info,source)
                else:archive.addfile(info)
    return dict(file=destination.name,sha256=digest(destination),compressed_bytes=destination.stat().st_size,seconds=time.monotonic()-begin)


def main():
    output=HERE/'layers';output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError('Layer destination must be empty; retain old evidence under another run directory')
    archive=ORIGINAL/'ds4-fc80bd6-source.tar.gz'
    if digest(archive)!=EXPECTED_SOURCE:raise ValueError('Source archive digest mismatch')
    state=Path(tempfile.mkdtemp(prefix='ds4-selected-rootfs-',dir='/tmp'))
    root=state/'root';root.mkdir()
    receipt=dict(source_image=IMAGE,state=str(state),phases=[])
    cid=subprocess.check_output(['docker','create',IMAGE],text=True).strip()
    begin=time.monotonic()
    try:
        with (state/'full-rootfs.tar').open('wb') as target:
            subprocess.run(['docker','export',cid],stdout=target,check=True)
        subprocess.run(['tar','-xf',str(state/'full-rootfs.tar'),'-C',str(root),'--no-same-owner','--anchored','--exclude=dev/*','--exclude=proc/*','--exclude=sys/*'],check=True)
    finally:
        subprocess.run(['docker','rm',cid],check=True,stdout=subprocess.DEVNULL)
    receipt['phases'].append(dict(name='export-source-rootfs',seconds=time.monotonic()-begin))
    members=set()
    with tarfile.open(archive) as source:
        for member in source:
            name=member.name.removeprefix('./').rstrip('/')
            if not name or name.startswith('/') or '..' in Path(name).parts:raise ValueError('Unsafe source archive path')
            members.add(name)
            path=root/'opt/ds4/source'/name
            if member.isfile():
                with source.extractfile(member) as data:
                    if hashlib.file_digest(data,'sha256').hexdigest()!=digest(path):raise ValueError('Changed pinned source: '+name)
            elif member.issym() and os.readlink(path)!=member.linkname:raise ValueError('Changed pinned source link: '+name)
    original_app={name:digest(root/'opt/ds4/bin'/name) for name in APPS}
    app_output=state/'stripped';app_output.mkdir()
    subprocess.run(['docker','run','--rm','--network','none','--entrypoint','/bin/sh',
                    '-v',str(root/'opt/ds4/bin')+':/input:ro','-v',str(app_output)+':/output',IMAGE,
                    '-c','set -eu; for name in ds4 ds4-bench ds4-server ds4-eval ds4-agent; do objcopy --strip-debug /input/$name /output/$name; done'],check=True)
    for name in APPS:shutil.copy2(app_output/name,root/'opt/ds4/bin'/name)
    groups={name:set() for name in ('os','cuda-runtime','compiler','source','app','metadata','objects')}
    unique_bytes={name:0 for name in groups};seen=set()
    for directory,dirs,files in os.walk(root,followlinks=False):
        for base in dirs+files:
            path=Path(directory)/base;name=str(path.relative_to(root));s=path.lstat()
            if stat.S_ISDIR(s.st_mode):continue
            group=select(name,members)
            if group is None:continue
            groups[group].add(name)
            if stat.S_ISREG(s.st_mode) and (s.st_dev,s.st_ino) not in seen:
                seen.add((s.st_dev,s.st_ino));unique_bytes[group]+=s.st_size
    # The source tree refers to the single canonical application copy. copytree
    # follows these links into a writable experiment workspace before rebuilding.
    for name in APPS:
        path=root/'opt/ds4/source'/name;path.unlink();path.symlink_to('/opt/ds4/bin/'+name)
        groups['source'].add('opt/ds4/source/'+name)
    bundle=json.loads((ORIGINAL/'bundle-manifest.json').read_text())
    bundle.update(bundle_kind='selected-component-layers',source_rootfs_image=IMAGE,
                  packaging_recipe_sha256=digest(Path(__file__)),weights_included=False)
    (root/'opt/ds4/bundle-manifest.json').write_text(json.dumps(bundle,indent=2)+'\n')
    (root/'opt/ds4/binaries.sha256').write_text(''.join(digest(root/'opt/ds4/bin'/n)+'  /opt/ds4/bin/'+n+'\n' for n in APPS))
    for name in ('bundle-manifest.json','binaries.sha256'):groups['metadata'].add('opt/ds4/'+name)
    for name in ('work','weights','outputs','proc','dev','sys','tmp','run','run/nvidia-driver','run/nvidia-driver/lib'):
        (root/name).mkdir(parents=True,exist_ok=True);groups['os'].add(name)
    # Directory headers are explicit and identical across layers. Files have
    # exactly one owner; shared parent directories are harmless OCI entries.
    for group,paths in groups.items():
        for name in list(paths):
            for parent in Path(name).parents:
                if str(parent)!='.':paths.add(str(parent))
    receipt.update(original_application_sha256=original_app,source_members=len(members),
                   logical_unique_file_bytes=unique_bytes,layers={})
    for group,paths in groups.items():
        receipt['layers'][group]=write_layer(root,paths,output/(group+'.tar.gz'))
        print(group,receipt['layers'][group]['compressed_bytes'],flush=True)
    (HERE/'selection-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (HERE/'path-ownership.json').write_text(json.dumps({group:sorted(paths) for group,paths in groups.items()},indent=2)+'\n')
    print('Retained source and curated inputs:',state,flush=True)

if __name__=='__main__':main()
