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

Proof: `npm install` + clean `tsc` + `cdk synth` produced all three templates
(cv-dev-data, cv-dev-api, cv-dev-hosting) on the first run. No failures this
phase, so no symptom/root-cause entries yet.

### Early deploy (2026-07-31, same day)

Deployed the scaffold to AWS immediately instead of waiting for step 8, so a
reachable URL exists from day one. One pass, no failures, 486s total:

- Site: https://d2huf9zo4vm99c.cloudfront.net (honest empty state, config.js
  injected with the API base)
- API: https://styvk0z2zd.execute-api.us-east-1.amazonaws.com/dev/ where
  GET /health returns ok with a live table_status ACTIVE against
  cv-convene-dev, proving API Gateway, Lambda, IAM, and the table are wired
  end to end
- One warning to keep an eye on, not a failure: cdk noted the
  crossStackReferencesDefaultStrong construct annotation on cv-dev-api.
  Same behaviour study-conscience deploys with; nothing to fix now.

## Phase 2: Google Calendar OAuth + secrets (2026-07-31)

**Symptom:** the plan said "reuse the refresh-token pattern from standup-brief",
but Secrets Manager has no standup-brief/google-oauth secret.
**Root cause:** standup-brief never minted its refresh token; its own BUILD_LOG
records the secret as "doesn't exist yet" and its calendar ran as unavailable.
**Fix:** reuse the surviving piece, the Desktop OAuth client (project
standup-brief, client JSON still in ~/Downloads) plus its one-time
get_refresh_token.py approach, and mint the token now for convene.
**Reasoning:** the pattern was proven, the credential was not. Reusing the
client avoids a new Google Cloud project and consent screen from scratch.

**Symptom:** first consent attempt failed with Google's "access blocked, app
not verified" page before the Allow button.
**Root cause:** the OAuth consent screen is in Testing mode, and the
calendar-owning account was not on the test-user list. This is almost
certainly the same wall that stopped standup-brief's token from ever being
minted.
**Fix:** added the account as a test user (console, Audience page); consent
then went through with the expected unverified-app interstitial.
**Reasoning:** fastest unblock for a solo tool. Known cost, logged before it
bites: Testing-mode refresh tokens expire after 7 days, which covers the
Aug 3 deadline but not life after it. Publishing the app removes the expiry
and is the post-deadline fix.

Also this phase, two smaller checks:

- Gemini key stored as convene/gemini and verified with a live
  generateContent call. The gating memory from study-conscience has widened:
  gemini-2.5-flash AND the *-latest aliases all 404 for this key even though
  models.list shows them. gemini-3.5-flash answered HTTP 200 for real, so it
  is the default model id (still overridable with -c model=...). Lesson:
  verify per key with a real call; models.list is not evidence.
- Telegram creds copied to convene/telegram from study-conscience (same bot,
  chat id confirmed matching).

Secrets now in place: convene/gemini, convene/google-oauth (client id +
secret + refresh token, calendar.readonly), convene/telegram. Verified by a
real calendarList read: 4 calendars visible, but none of them is an
academic/community pair yet; which calendars play those roles is the owner's
call, pending at time of writing.
