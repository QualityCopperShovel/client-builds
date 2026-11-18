from pathlib import Path
import os

path = Path('launch_check.py')
text = path.read_text()
old = "run('xcodebuild', '-project', 'ExcessiveCode.xcodeproj'"
new = "run('xcodebuild', '-showBuildTimingSummary', 'COMPILATION_CACHE_ENABLE_CACHING=YES', 'COMPILATION_CACHE_ENABLE_DIAGNOSTIC_REMARKS=YES', 'COMPILATION_CACHE_KEEP_CAS_DIRECTORY=YES', " + repr("COMPILATION_CACHE_CAS_PATH=" + os.path.join(os.environ["GITHUB_WORKSPACE"], "swift-cas")) + ", '-project', 'ExcessiveCode.xcodeproj'"
assert text.count(old) == 1
path.write_text(text.replace(old, new))
