# iPhone build runner

Use the standard macOS 15 Intel runner for iPhone TestFlight uploads.

Run 41511969406 never acquired a hosted runner. GitHub reported arm64 capacity
constraints and cancelled the job before any build step ran. The standard
macos-15-intel label uses the x64 pool and includes Xcode 26.3. The existing
workflow still checks the installed Xcode version before archiving.

Native source snapshots, signing, deadlines, upload and receipt checks stay in
the same workflow. After an unstarted run fails, dispatch the same private source
and build number with the corrected workflow; do not rerun the old runner config.
Client source and source artifacts must never be added to this public repository.
