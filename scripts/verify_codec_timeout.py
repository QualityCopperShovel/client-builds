import json, os, pathlib, subprocess, sys, time
out=pathlib.Path('codec-evidence'); out.mkdir(exist_ok=True)
code="import subprocess,time; subprocess.Popen(['sleep','60']); time.sleep(60)"
t=time.monotonic()
p=subprocess.run([sys.executable,'workflow/scripts/run_with_timeout.py','1',sys.executable,'-c',code],capture_output=True,text=True,timeout=6)
elapsed=time.monotonic()-t
result={'platform':sys.platform,'exit':p.returncode,'elapsed':elapsed,'pipes_closed':True,'stderr':p.stderr}
(out/'descendant-timeout.json').write_text(json.dumps(result,indent=2))
assert p.returncode==124 and elapsed<5, result
print(json.dumps(result))
