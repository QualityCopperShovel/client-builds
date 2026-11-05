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

Validation starts the simulator before compiling and waits for readiness only before the simulator build.

Run 42073228317 built the device app, then timed out during first-run migration
(LaunchServices and MCProfile), before any app or UI test could run. The passing
baseline 42070155210 used the same Intel label and iPhone 17 device. Its migration
also ran close to the deadline. This is infrastructure failure, not a UIKit result.

Preboot alone failed in run 42075758783: the seeded iPhone 17 on iOS 26.2
again timed out in LaunchServices migration. Preboot memory had no compression or
swap, and the writable disk had 108 GiB free. Compiler pressure is not a supported
explanation for this second failure.

Validation now creates one fresh iPhone 16 on installed iOS 18.6. The retained
runtime manifest confirms that runtime is available and supports the device and
both runner architectures. This isolates the seeded 26.2 migration path; it is a
repair to validate, not a proven UIKit pass. Never use known-broken 18.5 or silently
fall back when 18.6 is absent. TestFlight stays on the distribution toolchain and
is not gated on this infrastructure repair.

Run 42082067159 used the same image, runtime and device, yet LaunchServices
migration was still running at 162 seconds; in 42078029818 it ended near 77
seconds and full readiness came at 114. First-boot migration speed varies by
machine, so an idle wait at job start is fragile. `simctl boot` now returns while
migration continues during Swift tests and the device build (about ten minutes).
Readiness is checked just before the simulator build, with 300 seconds left.

Keep the 30-second create, 60-second boot and 300-second readiness limits. Retain
selection, runtime, memory, disk and boot progress in the existing artifact so a
timeout leaves evidence even if combined GitHub logs omit the failed step. A failed boot
start or readiness wait stops later steps, and always-run upload keeps
evidence. Do not retry a failed boot within the same job.

## Job budget

The job cap must exceed the sum of every step deadline, so a slow step fails with its own log.

Run 42078029818 proved the iOS 18.6 repair: the fresh device booted in 144 seconds,
the app launched, and XCTest started the first UI test. GitHub then cancelled the
job at its 20-minute cap, 98 seconds into UI tests, with no test verdict. The cap
was smaller than the steps' own deadlines, and `swift test` had none.

Every step has its own deadline: boot start 120 s, readiness 300 s, `swift test` 600 s, each build 360 s,
direct launch about 110 s, UI tests 600 s and evidence capture about 90 s. The job
cap of 50 minutes covers their sum plus checkout, upload and runner shutdown. A
slow step must fail on its own deadline with its own log, never on the job cap.
When adding or lengthening a step, keep this sum under the cap.
