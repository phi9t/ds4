from pathlib import Path
import subprocess, shutil, json, hashlib
project=Path('/work/packaging')
shutil.copytree('/opt/ds4/bazel/project',project)
inputs=project/'inputs';inputs.mkdir()
apps=['app-ds4','app-ds4-bench','app-ds4-server','app-ds4-eval','app-ds4-agent']
names={'runtime':['os','cuda-runtime']+apps+['metadata'],'build':['os','cuda-runtime','compiler','bazel-tools','source']+apps+['metadata']}
for n in names['build']:(inputs/(n+'.tar.gz')).symlink_to('/layers/'+n+'.tar.gz')
records={}
for stage in ['baseline','edited']:
 if stage=='edited':
  for n in ['source','app-ds4-bench']:
   link=inputs/(n+'.tar.gz');link.unlink();link.symlink_to('/edited/'+n+'.tar.gz')
 env=dict(__import__('os').environ,DS4_BAZEL_WORK_ROOT='/work/cache-'+stage)
 subprocess.run(['./compose-offline.sh'],cwd=project,env=env,check=True)
 records[stage]={}
 for kind,order in names.items():
  layout=project/'bazel-bin'/(kind+'_image')
  subprocess.run(['./verify-layout.py',str(layout),str(inputs),*order],cwd=project,check=True)
  digest=json.loads((layout/'index.json').read_text())['manifests'][0]['digest']
  manifest=json.loads((layout/'blobs/sha256'/digest.split(':')[1]).read_text())
  records[stage][kind]={'manifest':digest,'layers':dict(zip(order,manifest['layers']))}
changed={}
for kind in names:
 left=records['baseline'][kind]['layers'];right=records['edited'][kind]['layers']
 changed[kind]=[name for name in names[kind] if left[name]['digest']!=right[name]['digest']]
assert changed=={'runtime':['app-ds4-bench'],'build':['source','app-ds4-bench']}
report={'scope':'Synthetic source/application fixture substitution; no source compilation or CUDA validation claimed. Real live clean compilation is independently recorded by the main agent.','network':'none','rootfs':'read-only','vendor_template':'read-only','fresh_output_roots':True,'substituted_inputs':['source','app-ds4-bench'],'changed_layers':changed,'unchanged_layers_verified':True,'records':records}
Path('/proof/source-edit-fixture.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'source_edit_fixture':'passed','changed_layers':changed}))
