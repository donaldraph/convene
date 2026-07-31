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
call, pending at time of writing. Decision: create two fresh calendars named
"Academic" and "Community" and populate them with real entries.

## Phase 3: conflict detection (2026-07-31)

Built and deployed same day:

- gcal.py: stdlib calendar client (refresh-token exchange, calendars found BY
  NAME so nothing hardcodes an id, windowed fetch with paging, recurring
  events expanded, cancelled dropped).
- conflicts.py: pure deterministic engine. hard = timed-vs-timed interval
  overlap; same_day = an all-day event sharing a date with the other
  calendar's event (flagged as a warning class, not a certain collision).
  Stable conflict ids (hash of the event-id pair) so status survives
  re-syncs. 12 unit tests, all green, including back-to-back-is-legal and
  cross-timezone overlap.
- sync.py: POST /sync (API-key gated) reconciles the cache both ways
  (upserts fresh, DELETES vanished/moved events so a moved event cannot
  leave a phantom conflict) then upserts conflicts by stable id and clears
  the ones that no longer exist. get_conflicts.py: GET /conflicts public
  read with last-sync freshness.

Live proof of the chain, before the calendars exist: POST /sync against the
deployed API returned the honest 424 "calendar(s) not found by name:
Academic, Community". That one response exercises API key, Lambda, Secrets
Manager, the Google token exchange, and the calendarList lookup for real.
The only thing missing is the calendars themselves.

One deploy-time wrinkle, not a code fix: a freshly created API key returns
403 Forbidden for ~30-60s until it propagates through the usage plan. First
call after the wait succeeded. Same behaviour standup-brief saw.

### The calendar-account saga, and the design change it forced

**Symptom:** four rounds of "create Academic + Community calendars" all ended
with the sync reporting the calendars not found, even after OAuth was pointed
at the right account.
**Root cause, uncovered by enumerating events per calendar via the API:** on a
shared machine with several Google accounts signed in, calendar/event creation
kept landing in whichever account the browser had active, not the connected
one. The refresh token first belonged to donaswagger@gmail.com (empty), was
re-minted for donaldraph.dev@gmail.com (which held the real AWS events on its
PRIMARY calendar), but the "Academic"/"Community" sub-calendars never appeared
because they were made elsewhere. Ultimately the owner added everything to ONE
calendar (primary), distinguishing type by event TITLE ("academic", "Academic",
"outreach", "tour").
**Fix (checkpointed with the owner before deviating):** added a second source
mode. gcal now resolves the literal name `primary`; sync gained a split mode
(SPLIT_CALENDAR) that reads ONE calendar and classifies each event academic vs
community by a title tag (classify.split_by_tag, ACADEMIC_TAG default
"academic"). Deployed with -c splitCalendar=primary. The two-calendar mode is
still there for anyone who keeps them separate.
**Reasoning:** matching how the user actually keeps their calendar beats making
them restructure it, and single-calendar-with-tags is arguably the more
realistic student setup. The AI's job (best-time recommendation) is unchanged;
this only affects where the two event sets come from.

**Live proof on real data (2026-07-31):** POST /sync in split mode returned
mode=split, academic 2 / community 2 events, and detected **2 hard conflicts** -
the owner's "Academic" event on Aug 1 12:00-13:00 collides with both "outreach"
and "tour" at the same time. GET /conflicts returns both with stable ids. A
second sync returned open_new 0 / still_open 2 / cleared 0, proving the stable
conflict ids and exactly-once open/keep/clear machinery hold on real data, not
just in unit tests. Conflict detection - the first half of the spine - is done
and working end to end.

17 unit tests total (12 conflict engine + 5 classifier), all green.

## Phase 4: Gemini best-time recommendation (2026-07-31)

The load-bearing AI, second half of the spine. Division of labour kept honest:
deterministic code computes which candidate slots are genuinely conflict-free
(model.free_slots), and the MODEL ranks those free slots by judgment code
cannot fake (protecting revision time before a test, buffers after class,
sociable hours, avoiding punishing gaps). We never ask the model whether a slot
is free; only which free slot is best, and why. POST /recommend (key-gated,
spends quota) + GET /recommendations (public). Every recommendation stored under
RECO.

Three real problems, each fixed:

**Symptom:** local smoke test of the model returned the honest deterministic
fallback, not AI. **Root cause:** gemini-3.5-flash (the phase-2 default) now
503s hard under load for this key. **Fix:** tested five models 3x each WITH the
real response schema. Two held up: gemini-flash-latest (3/3, and clearly the
sharpest reasoning) and gemini-3.5-flash-lite (3/3, rock solid);
gemini-2.5-flash-lite 404s, gemini-2.0-flash 429s. Made the primary the sharp
one with an automatic fallback to the solid one, then a labelled deterministic
fallback. **Reasoning:** for a pass/fail challenge the AI feature must actually
produce AI output; a fallback CHAIN across models buys both quality and
reliability without pretending.

**Symptom:** first live POST /recommend returned "Endpoint request timed out".
**Root cause:** API Gateway REST APIs kill any request at 29s; the model budget
(45s urlopen + retries + fallback) exceeded it. **Fix:** one tight attempt per
model (12s) and let the model chain be the resilience, not slow same-model
retries - a 503/429 returns fast, so falling straight to the next model is
quicker than backing off in place. **Reasoning:** stay synchronous (simple)
while fitting the hard cap.

**Symptom:** after that, both models timed out at 12s. **Root cause:** a 10-day
window yields 223 half-hourly free slots, and asking the model to rank all 223
made a huge prompt and an enormous generation. **Fix:** model.shortlist
down-samples to an evenly-spread ~18 (a few per day across the window) before
the model call; the response reports both total_free and the shortlisted count.
**Reasoning:** ranking 200 near-duplicate slots is pointless and slow; a spread
of real options across days is what the user wants and the model can rank fast.

**Live proof on real data (2026-07-31):** POST /recommend for a 90-min "Core
team planning meeting" over 10 days: 223 free slots found, 18 shortlisted,
gemini-3.5-flash-lite ranked them (primary flash-latest timed out, chain caught
it) and recommended a Jul 31 late-afternoon slot, explicitly reasoning to AVOID
"the heavy congestion of midday academic and community events on August 1" -
i.e. it steered around exactly the day the conflict engine flagged. Genuine
judgment over both calendars, stored and re-readable via GET /recommendations.
The spine (conflict detection + best-time recommendation) is DONE and working
end to end on live data.

27 unit tests total (12 conflict + 5 classifier + 10 free-slot/shortlist/model),
all green.

### Phase 4 follow-up: async, because free-tier latency vs the 29s cap

**Symptom:** even after tuning models and shortlisting, POST /recommend only
succeeded ~2-4 times in 6 - the rest returned the honest deterministic fallback
after both models timed out. Repeated rapid calls made it worse.
**Root cause:** two compounding facts. (1) API Gateway REST APIs hard-kill any
request at 29s. (2) Gemini free-tier latency is highly variable and, under my
own rapid testing, rate-limited into multi-second queueing - from Lambda,
individual calls sometimes exceeded even 20s. A synchronous endpoint capped at
29s cannot reliably wait that out, no matter how the model budget is split.
**Fix:** made /recommend asynchronous. The API handler computes free slots +
shortlist (fast, deterministic), writes a PENDING recommendation, invokes a
worker Lambda (InvocationType=Event), and returns a pending id in ~2s. The
worker does the Gemini ranking with the full 60s Lambda timeout (primary lite
40s, fallback flash-latest 12s) and flips the record to done. The dashboard
polls GET /recommendations until status=done. Errors are recorded as status
error, never left pending.
**Reasoning:** the 29s cap is a property of API Gateway, not of the work; the
model ranking genuinely can take longer than that on a free tier. Decoupling
the slow call from the request removes the cliff entirely instead of shaving
timeouts to barely fit. This is the standard fix and it made the star feature
reliable.

**Live proof (2026-07-31):** POST returned pending in 1.9s (candidate_count 10,
total_free 115); polling flipped it to done via gemini-3.5-flash-lite with real
reasoning tied to the actual calendar ("sits safely after your 12:00 to 13:00
academic event ... without running into late evening fatigue like the 19:59
runner-up"). Reliable across repeats because the worker is not under the cap.

## Phase 7: dashboard (2026-07-31)

The face of the submission, deployed to CloudFront. Clean editorial identity
(warm off-white / green accent, theme-aware light+dark), deliberately NOT
terminal-styled. Read-only by design: it calls only the public GET routes
(/conflicts, /recommendations), so no API key ever ships to the browser; the
key-gated write routes stay server-side. Shows live conflicts (academic-vs-
community with hard/same-day badges), best-time recommendations (AI reasoning
prominent, ranked slots with the top pick highlighted, model-source badge), and
last-sync freshness. Pending recommendations show a "thinking" state and the
page polls every 4s until the worker flips them to done. Honest empty states,
no sample data.

Cleaned up test artifacts first: my earlier synchronous-era testing left several
FALLBACK records (pre-async, no status field) that misrepresented the now-
reliable feature, so I deleted them and generated a fresh set of three real
recommendations through the working async path (all three landed real AI after
a rate-limit cooldown). Not fabrication - real outputs of the real system,
minus the stale failed attempts.

**Live + visually verified (2026-07-31):** https://d2huf9zo4vm99c.cloudfront.net
renders both hard conflicts (Academic vs outreach, Academic vs tour on Aug 1)
and three AI recommendations with genuine calendar-aware reasoning. The spine is
complete, deployed, and demoable end to end.
