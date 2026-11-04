# Mac staple recovery

Keep signed releases moving through Apple ticket network drops.

## Design

The existing Mac workflow retries staple and validate separately. Each has six attempts, a120-second call cap and15/30/45/60/75-second waits. Exhaustion fails the release. No signature, notarization or Gatekeeper check is skipped.

## Rules

Both app and disk image must pass. The existing60-minute sign-job deadline owns the full step. Native source stays in private snapshots; this workflow change does not change app code or its sample checks.

## Why

Mac run41819373707 attempt2 notarized successfully (Apple submission24dc1ba8-4f70-4139-b79e-e9f37b2004c9). Staple succeeded, but validation lost its CloudKit connection three times (NSURLErrorDomain -1005, error68).

The old combined loop restapled each time and stopped after three short waits. Separate retries preserve completed work and allow more recovery time, while keeping every release check.
