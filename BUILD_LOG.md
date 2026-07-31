# Build log

Every real problem hit during the build, in the order it happened. Format per
entry: symptom, root cause, fix, reasoning. No invented entries; if a phase
went clean, it says so.

## Phase 1: repo scaffold + CDK stacks (2026-07-31)

Decisions made up front, so later phases inherit them instead of relitigating:

- **Stack shape copied from study-conscience**, the most recently proven
  deploy of this exact pattern (CDK-TS data/api/hosting, Python 3.12 Lambdas,
  single DynamoDB table, private S3 behind CloudFront with OAC). Same pinned
  toolchain: aws-cdk-lib ^2.150.0, typescript ~5.5.4, node 22.
- **Gemini model id is a context flag, not a constant.** Pinned
  gemini-2.5-flash has 404'd for new accounts before; the *-latest aliases
  have not. Default is gemini-2.5-flash as specified, overridable with
  `-c model=...` at deploy so a gated model is a one-flag fix, not a code
  change. First live call will verify what the key can actually reach.
- **Conflict detection stays deterministic.** The model is only load-bearing
  for the best-time recommendation and conflict-resolution reasoning. No AI
  wrapped around plain overlap math.
- **API scaffold ships one real route (GET /health)** and nothing else. No
  501 theatre for routes that do not exist yet; routes land with the phase
  that implements them.
