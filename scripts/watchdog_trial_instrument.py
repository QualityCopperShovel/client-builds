from pathlib import Path

path = Path('launch_check.py')
text = path.read_text()
old = "run('xcodebuild', '-project', 'ExcessiveCode.xcodeproj'"
new = "run('xcodebuild', '-showBuildTimingSummary', '-project', 'ExcessiveCode.xcodeproj'"
assert text.count(old) == 1
path.write_text(text.replace(old, new))
