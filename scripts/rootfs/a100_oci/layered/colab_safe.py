"""Run Colab CLI without printing runtime proxy tokens in transport errors."""
import re
import subprocess
import sys
r=subprocess.run(['colab',*sys.argv[1:]],capture_output=True,text=True)
print(re.sub(r'colab-runtime-proxy-token=[^\s]+','colab-runtime-proxy-token=REDACTED',r.stdout+r.stderr))
raise SystemExit(r.returncode)
