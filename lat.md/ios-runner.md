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

Validation starts the simulator before its build and waits for readiness only before launching.

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
migration continues during the simulator build. Readiness is then checked with
300 seconds left.

Keep the 30-second create, 60-second boot and 300-second readiness limits. Retain
selection, runtime, memory, disk and boot progress in the existing artifact so a
timeout leaves evidence even if combined GitHub logs omit the failed step. A failed boot
start or readiness wait stops later steps, and always-run upload keeps
evidence. Do not retry a failed boot within the same job.

## Job budget

Each job's cap must exceed the sum of its step deadlines, so a slow step fails with its own log.

Run 42078029818 hit the old 20-minute cap 98 seconds into UI tests. Run 42084161049
then ran `swift test` beside simulator migration: the package build alone took 446
seconds and the 600-second bound fired before tests finished. One 4-core Intel
machine was compiling three times and migrating a simulator in sequence.

Validation now runs two parallel jobs on the chosen standard runner. `core` builds
package tests (720 s), runs them (300 s) and builds the Release device app (360 s),
capped at 30 minutes. `simulator` starts the device, builds for testing (540 s,
overlapping migration), waits for readiness (300 s), launches directly, runs UI
tests (600 s) and keeps evidence, capped at 35 minutes. A run passes only when both
jobs pass. When adding or lengthening a step, keep its job's sum under the cap.

## Simulator architecture

Build simulator tests only for the runner's architecture. Pass `ONLY_ACTIVE_ARCH=YES`
and `ARCHS="$(uname -m)"` to `build-for-testing` for the chosen device.

Run 42089772549 passed core tests and the device build but hit the 540-second
simulator build limit. Its log shows Swift dependency builds and app linking for
both arm64 and x86_64, even though the runner is Intel. The generated project
defaults include both; the chosen simulator does not need both binaries.
The workflow now restricts this validation build to the host chip. Device and
TestFlight builds keep their own settings. Step and job deadlines stay the same.

## Simulator discovery

Run 42092304293 timed out during the first `xcrun simctl list runtimes -j`
after 30 seconds, before device creation or compilation.

The retained JSON was empty. No CoreSimulator logs or resource samples were captured because the old
evidence step required a device ID. This does not establish why startup stalled
and does not test the host-only build change. Core tests and the device build passed.

Discovery now has its own step: tool lookup has 30 seconds and one cold-start
runtime query has 120 seconds. There is no retry or fallback runtime. These
bounds fit within the existing 35-minute simulator job cap. The longer first
query accommodates service startup; it is not a proven fix for the old timeout.
Start/end elapsed time, phase and status, stderr, memory and disk samples are
retained. Any failed simulator job also captures process state and up to 200
CoreSimulator service log lines, even before a device exists. These logs can
distinguish tool lookup failure from a stalled service query on the next run.

## Simulator app startup

Install and launch are separate traced phases with 90-second and 60-second limits. Neither retries in the same job; the existing 35-minute cap still exceeds the summed step limits.

Validation 42401402861 attempts 1 and 2 timed out in a combined install/launch step. Simulator logs reported the app installed after about 15 seconds, but no launch result was saved. This does not prove which call stalled or an app crash. Phase start/terminal elapsed time and exit status now close that gap. Wider cold-start bounds allow the next call to finish or fail by name; they do not establish the old cause.

Startup failure evidence includes installcoordinationd and installd for this bundle. The artifact name includes the run attempt: two old attempt artifacts had the same name, and downloading by run returned the first one's files. Preserve exact attempt identity when reviewing a rerun.

## One launch owner

Source: https://github.com/QualityCopperShovel/client-builds/actions/runs/42490209952 (2026-11-08).

The merged 0.35.1 source passed core tests and both device and simulator compilation. The independent simctl launch preflight timed out after 60 seconds before XCTest ran. The retained screenshot shows the Home Screen and launch events show installation; no app launch or crash is established. Its deeper stall cause remains unknown.

Drop the duplicate simctl launch preflight. XCTest remains the one launch owner: the existing fresh-install case launches the app and requires the live web UI to render, and later cases launch it again for interaction checks. Keep the 600-second test owner and 180-second case limit, failure evidence and source-pinned artifact. Record XCTest start, terminal status and elapsed time in the existing startup evidence. This retains the behavior check while removing a second launch path that can block it.


## Interactive simulator startup

Interactive sessions bound and trace boot readiness, install, permissions and launch before handing control to the agent. Native compilation is separate evidence.

Run https://github.com/QualityCopperShovel/client-builds/actions/runs/42724593352 compiled the exact native candidate and saved its app cache, then spent about 22 minutes in the combined Install and open step before owner cancellation. No substep markers were saved. Boot readiness and install had wrappers; both privacy calls and launch were unbounded. The exact stalled call and CoreSimulator cause remain unknown.

The same run's retained relay artifact says exit reason=idle before handoff. This does not explain the simctl stall. The relay's idle clock started during build preparation and could expire before an agent received control. With a workflow-owned handoff marker, the existing watchdog begins idle expiry only after the handoff artifact is uploaded. The original absolute DEADLINE remains active throughout preparation; it is never reset or enlarged. Relays without the marker retain their old behavior.

Interactive startup now gives the five existing commands fixed labels and per-call limits (300, 90, 20, 20 and 60 seconds), sharing one 420-second monotonic deadline. A stalled permission call stops startup; non-timeout permission errors retain their prior optional behavior. The existing timeout helper saves running and terminal status, elapsed time and exit code in startup.jsonl without arguments, paths, environment or content. Boot progress and startup metadata join the existing always-uploaded session evidence. This names the failed boundary on the next authorized run; it does not prove the old stall is repaired.

The app cache key, source snapshot SHA, runtime selection, job cap and requested session lifetime are unchanged. A future authorized check can reuse the built app. This repair itself dispatches no build and does not upload to TestFlight.


## Simulator request deadlines

The relay and its client share one request budget, including queue wait, AXe recovery and response margin. A slow UI read must end by name before its caller gives up.

Run https://github.com/QualityCopperShovel/client-builds/actions/runs/42729960812 restored the exact built app, completed all startup stages and handed off. The fixture launch took about 10 seconds. The driver stopped waiting for /ui after 30 seconds; the relay logged a bridge restart and returned HTTP 502 after about 35 seconds. The artifact does not retain that exception, so the deeper AXe failure remains unknown. The old recovery allowed a 60-second command, a 20-second bridge stop, and up to five more attempts without an overall request deadline.

The existing relay request owner now consumes X-Simulator-Timeout-Seconds, or bounded defaults for older clients. It reserves transport margin and caps work by the unchanged session deadline. The action lock, subprocesses and bridge recovery consume that same monotonic budget. Stop no longer waits behind an action. Fixed stage/state/request-ID metadata is retained without arguments, output or environment. Timeout replies carry HTTP 504 and a named stage; disconnected response delivery is cancelled in the log rather than relabeled as an AXe failure. The canonical simulator client propagates its existing HTTP timeout and reports structured terminal steps. Driver phase budgets must also cap each call by the remaining phase time.

Native source 1c5 and its app cache stay unchanged. This repair runs only local relay/client fixtures; it starts no hosted build and claims no WK delegate pass. The old hosted simulator was stopped by cleanup, so a later authorized check must use the saved app cache rather than pretending that session is live.

## Installer failure evidence

[Run 42734946682](https://github.com/QualityCopperShovel/client-builds/actions/runs/42734946682)
restored the pinned simulator app. Boot readiness took about 170 seconds. The
install then used its full 90-second cap and timed out. The saved artifact lacked
installer-service evidence, so the CoreSimulator cause remains unknown.

On install failure, `scripts/capture_install_failure.py` writes one
`install-failure.json` to the existing always-uploaded session evidence artifact.
It appends running and terminal `install_evidence` rows to `startup.jsonl`. The
original install exit code remains the workflow result; capture cannot turn a
failed install into success. There is no retry.

The snapshot shares at most 15 seconds across process state, memory, disk, device
installer errors and host CoreSimulator errors. Both the existing 420-second
startup deadline and absolute session deadline cap that allowance. An exhausted
budget launches no commands and still saves terminal metadata. Each subprocess
has a smaller cap; timeout kills its process group. Input is bounded to 256 KiB
per command, with at most 100 service records and 32 process rows retained.

Only fixed service names, numeric process/resource fields, allowlisted error
domains and codes, and fixed message flags reach the artifact. Raw service
messages, paths, arguments, environment, app content and identities are omitted.
Flags describe matched error text, not a proved cause. This closes an evidence
gap; it does not claim to fix the old install stall or prove native Back behavior.

## Public relay handoff health

[Run 42739322133](https://github.com/QualityCopperShovel/client-builds/actions/runs/42739322133)
restored the cached app and completed install and launch. The final public health
check returned HTTP 530, so no handoff or native cases ran.

The earlier relay health response was 200. The saved artifact has no tunnel error body, so the
precise Cloudflare fault remains unknown. This was not an SDK compile failure.

The existing final handoff check now owns readiness; the detached early health
poller is removed. `wait_relay_health.py` reads a bounded tunnel-log tail and
excludes the provider API hostname. A 200 reply must be JSON with `ok: true` and
the exact original relay deadline. Only then is the private tunnel address saved
for encryption. Body text, addresses and tokens never enter saved metadata.

The existing 120-second address-wait allowance now includes health retries.
The original 420-second startup deadline is saved across workflow steps and caps
handoff too, as does the original absolute session deadline. Curl keeps its
five-second per-call cap. Fixed transient HTTP statuses (including 530) and
transport failures may retry after at most one second; other failures and invalid
relay replies fail immediately. Exhausted deadlines make no calls. The existing
timeout helper owns the terminal handoff state; per-attempt HTTP/exit codes and
elapsed time join `startup.jsonl` in the existing artifact. No job, runtime, build
or session bound is increased. This repair does not dispatch a hosted run.
