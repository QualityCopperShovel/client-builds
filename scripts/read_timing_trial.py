from pathlib import Path

path = Path('launch_check.py')
s = path.read_text()
def replace(old, new):
    global s
    assert s.count(old) == 1, old
    s = s.replace(old, new)

old = "const request=(action,extra={})=>timeout(voice.postMessage({action,authorization:token,client,...extra}),action);"
new = '''let traceSequence=0;
const tracedVoice=(body)=>{
 const id=++traceSequence, action=body.action, phase=body.authorization===token+'-burst'?'burst':body.authorization===token?'base':'other';
 if(action==='read')report({read_timing:{id,phase,event:'start',at:Date.now()}});
 const promise=voice.postMessage(body);
 if(action==='read')promise.then(()=>report({read_timing:{id,phase,event:'reply',at:Date.now()}}),()=>report({read_timing:{id,phase,event:'reject',at:Date.now()}}));
 return promise;
};
const request=(action,extra={})=>timeout(tracedVoice({action,authorization:token,client,...extra}),action);'''
replace(old,new)
replace("timeout(voice.postMessage({action:'read',authorization:token+'-burst',client}),'read')", "timeout(tracedVoice({action:'read',authorization:token+'-burst',client}),'read')")
old="                    if value.get('ping'):\n"
replace(old,"                    if value.get('read_timing'):\n                        evidence.setdefault('read_timing', []).append(value['read_timing'])\n"+old)
old='''            time.sleep(delay if self.path.endswith('/preference') else .15)
            self.respond({'enabled': True, 'microphone': True})'''
new='''            started = time.time()
            auth = self.headers.get('Authorization', '')
            phase = 'burst' if auth.endswith('launch-fixture-burst') else 'base' if auth.endswith('launch-fixture') else 'other'
            sample = {'started': started, 'path': 'preference' if self.path.endswith('/preference') else 'other', 'phase': phase}
            evidence.setdefault('fixture_get', []).append(sample)
            try:
                time.sleep(delay if self.path.endswith('/preference') else .15)
                self.respond({'enabled': True, 'microphone': True})
                sample.update(outcome='response_written', finished=time.time())
            except (BrokenPipeError, ConnectionResetError):
                sample.update(outcome='disconnected', finished=time.time())
                raise'''
replace(old,new)
old="        if sim:\n            try:\n                subprocess.run(['xcrun', 'simctl', 'terminate', sim, 'com.fairystack.ios'], capture_output=True, timeout=15)"
new="        if container:\n            try:\n                evidence['authorization_timing'] = (container / 'Library/Caches/launch-auth-timing.log').read_text().splitlines()[-200:]\n            except OSError:\n                pass\n"+old
replace(old,new)
path.write_text(s)

path = Path('Shared/Voice/VoiceRecorder.swift')
s = path.read_text()
old='''        authorizing = pending
        try await pending.value
    }
    private func admit'''
new='''        authorizing = pending
        // Isolated simulator trial: synthetic fixture phases only; never store credentials.
        let trial = ProcessInfo.processInfo.environment["EXCESSIVECODE_LAUNCH_CHECK"] != nil
        let phase = authorization == "launch-fixture" ? "base" : authorization == "launch-fixture-burst" ? "burst" : "other"
        let trace = UUID().uuidString
        func sample(_ state: String) {
            guard trial else { return }
            let url = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("launch-auth-timing.log")
            let line = "\\(Date().timeIntervalSince1970) \\(trace) \\(phase) \\(state)\\n"
            if !FileManager.default.fileExists(atPath: url.path) { FileManager.default.createFile(atPath: url.path, contents: nil) }
            if let file = try? FileHandle(forWritingTo: url) {
                defer { try? file.close() }
                _ = try? file.seekToEnd(); try? file.write(contentsOf: Data(line.utf8))
            }
        }
        sample("start")
        do { try await pending.value; sample("success") }
        catch { sample("failure"); throw error }
    }
    private func admit'''
assert s.count(old)==1
path.write_text(s.replace(old,new))
