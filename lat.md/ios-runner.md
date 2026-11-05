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

## Simulator first boot

Validation boots the chosen simulator before Swift tests and device compilation.

Run 42073228317 built the device app, then timed out during first-run migration
(LaunchServices and MCProfile), before any app or UI test could run. The passing
baseline 42070155210 used the same Intel label and iPhone 17 device. Its migration
also ran close to the deadline. This is infrastructure failure, not a UIKit result.

Preboot avoids compiler cache pressure during migration; that is a repair hypothesis,
not proof of the old cause. Keep the 60-second boot and 180-second readiness limits.
Retain runtime, memory, disk and boot progress in the existing screenshots artifact
so a timeout leaves evidence even when GitHub's combined logs omit a failed step.
Boot runs synchronously: failure prevents builds/tests and the always-run artifact
step keeps the evidence. Do not retry a failed boot within the same job.
