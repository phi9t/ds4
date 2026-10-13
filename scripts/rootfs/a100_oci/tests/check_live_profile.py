"""Verify published blobs and offline packaging on Linux without projecting a GPU."""
from pathlib import Path
import argparse
import base64,hashlib,json,os,subprocess,tempfile,time,sys
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--layers',type=Path,required=True,help='Verified component tar directory')
parser.add_argument('--crane',type=Path,required=True)
parser.add_argument('--state-parent',type=Path,required=True)
parser.add_argument('--docker-config',type=Path,required=True)
args=parser.parse_args()
repo=Path(__file__).resolve().parents[4]
profile=repo/'scripts/rootfs/a100_oci'
evidence=repo/'docs/rootfs/colab-oci/evidence'
args.state_parent.mkdir(parents=True,exist_ok=True)
state=Path(tempfile.mkdtemp(prefix='ds4-oci-landing-check-',dir=args.state_parent))
crane=args.crane.resolve(strict=True)
release=json.loads((evidence/'release.json').read_text())
records=[]
def run(name,argv,**kwargs):
    start=time.monotonic()
    with (state/(name+'.log')).open('w') as stream:
        result=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT,timeout=300,**kwargs)
    records.append(dict(name=name,seconds=time.monotonic()-start,returncode=result.returncode))
    if result.returncode:raise RuntimeError(name+' failed: '+str(state/(name+'.log')))
    print(name,'passed',flush=True)
try:
    run('portable-tests',['python3',str(profile/'tests/test_profile.py')],cwd='/tmp')
    cache=state/'cache';cache.mkdir()
    for image in release['images'].values():
        for name,descriptor in zip(image['layer_names'],image['layers']):
            destination=cache/descriptor['digest']
            if not destination.exists():
                source=args.layers/(name+'.tar.gz')
                try:os.link(source,destination)
                except OSError as error:
                    import errno,shutil
                    if error.errno!=errno.EXDEV:raise
                    shutil.copyfile(source,destination)
    env=dict(os.environ,DOCKER_CONFIG=str(args.docker_config.resolve(strict=True)))
    run('restored-build',['python3',str(profile/'layered/restore_layers.py'),'--release',str(evidence/'release.json'),'--image','build','--cache',str(cache),'--rootfs',str(state/'root'),'--logs',str(state/'restore'),'--crane',str(crane)],env=env)
    root=state/'root';work=state/'work';work.mkdir()
    def launch(name,args):
        run(name,['python3',str(profile/'launch_insula.py'),'--rootfs',str(root),'--work',str(work),'--weights',str(state/'weights'),'--outputs',str(state/name),'--',*args])
        receipt=json.loads((state/name/'insula-run-receipt.json').read_text())
        assert receipt['devices']==[] and receipt['driver_libraries']=={} and receipt['returncode']==0
    for app in ('ds4','ds4-bench','ds4-server','ds4-eval','ds4-agent'):
        launch('help-'+app,['/opt/ds4/bin/'+app,'--help'])
    (work/'probe.cu').write_text('__global__ void probe(int *p) { *p=42; }\n')
    launch('compile-sm80',['/usr/local/cuda/bin/nvcc','-arch=sm_80','-cubin','/work/probe.cu','-o','/work/probe.cubin'])
    launch('inspect-sm80',['/usr/local/cuda/bin/cuobjdump','--dump-sass','/work/probe.cubin'])
    assert 'sm_80' in (state/'inspect-sm80.log').read_text()
    packaging=work/'packaging';import shutil
    shutil.copytree(profile/'layered/bazel',packaging,ignore=shutil.ignore_patterns('bazel-*','inputs','__pycache__'))
    inputs=packaging/'inputs';inputs.mkdir()
    for name,descriptor in zip(release['images']['seed']['layer_names'],release['images']['seed']['layers']):
        os.link(cache/descriptor['digest'],inputs/(name+'.tar.gz'))
    launch('offline-compose',['/usr/bin/env','DS4_BAZEL_WORK_ROOT=/work/bazel-state','/bin/sh','/work/packaging/compose-offline.sh','//:runtime_image','//:build_image','//:seed_image'])
    # Relative OCI blob symlinks require the rootfs /work path when inspecting host-side.
    # Inspect inside the launcher where those paths remain meaningful.
    code="import hashlib,json; from pathlib import Path; r=json.loads(Path('/work/release.json').read_text()); result={};\nfor n in ('runtime','build','seed'):\n p=Path('/work/packaging/bazel-bin')/(n+'_image'); i=json.loads((p/'index.json').read_text()); d=i['manifests'][0]['digest']; assert d==r['images'][n]['digest']; m=json.loads((p/'blobs/sha256'/d[7:]).read_text());\n for x in m['layers']:\n  f=(p/'blobs/sha256'/x['digest'][7:]).open('rb'); assert hashlib.file_digest(f,'sha256').hexdigest()==x['digest'][7:]; f.close()\n result[n]=d\nPath('/outputs/manifests.json').write_text(json.dumps(result,indent=2))"
    (work/'release.json').write_text(json.dumps(release))
    launch('inspect-manifests',['/usr/bin/python3','-c',code])
    manifests=json.loads((state/'inspect-manifests/manifests.json').read_text())
    tools=state/'tools';(tools/'bin').mkdir(parents=True)
    shutil.copy2(root/'opt/ds4/bin/bazel',tools/'bin/bazel')
    shutil.copy2(root/'opt/ds4/bin/bazel.LICENSE',tools/'bazel.LICENSE')
    shutil.copytree(root/'opt/ds4/bazel/vendor',tools/'vendor',symlinks=True)
    run('package-tools',['python3',str(profile/'layered/package_tools.py'),'--tools',str(tools),'--output',str(state/'new-bazel-tools.tar.gz')])
    with __import__('tarfile').open(state/'new-bazel-tools.tar.gz') as archive:
        assert archive.getmember('opt/ds4/bin/bazel').isfile()
        assert not any(x.name.endswith('bazel-external') for x in archive)
    tested_sources={str(path.relative_to(repo)):hashlib.sha256(path.read_bytes()).hexdigest() for path in profile.rglob('*') if path.is_file() and path.suffix in ('.py','.sh','.bazel') and '__pycache__' not in path.parts}
    result=dict(tested_sources=tested_sources,status='passed',scope='fresh Linux builder integration; no Colab allocation, GPU projection, model inference or registry mutation',state=str(state),records=records,exact_published_manifests=manifests,cached_build_layers=11,source_commit='fc80bd695da76ee14bcb86820bf900a5cdfda806',python=sys.version.split()[0])
except BaseException:
    import traceback
    result=dict(status='failed',state=str(state),records=records,error=traceback.format_exc())
(state/'integration-results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2),flush=True)
raise SystemExit(0 if result['status']=='passed' else 1)
