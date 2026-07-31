# Convene

An AI student community assistant. Built for the AWS Builder Center "Weekend
Annoying Task Challenge" (publish window 31 Jul to 3 Aug 2026).

## The annoying task

As a Student Builder Group Leader I juggle two calendars: my academic calendar
(lectures, tests, deadlines) and my community-event calendar (sessions,
workshops, planning meetings). They collide, and every collision costs either a
class or the community. Planning a new event means eyeballing both calendars by
hand, and chasing my core team about their tasks by memory.

Convene does the juggling for me:

1. **Conflict detection**: reads both Google Calendars and flags every
   overlap between academic and community events. This part is deterministic
   code, on purpose. Overlap math is not an AI job.
2. **Best-time recommendation**: this is where the AI earns its place. Gemini
   reasons over both messy calendars and recommends conflict-free slots for a
   new event, judging trade-offs (buffer around tests, evening vs weekend,
   travel gaps) that plain date math cannot rank.
3. **Task assignment**: assign tasks to core team members, stored in DynamoDB
   with status tracking.
4. **Reminders**: EventBridge Scheduler triggers reminder sends via Telegram.

Features 1 and 2 are the spine. Features 3 and 4 ship only if they work
end-to-end; a missing feature beats a broken one.

## Architecture

Serverless on AWS, defined with CDK (TypeScript), three stacks:

- **data**: one DynamoDB table (single-table design) for cached calendar
  events, detected conflicts, recommendations, and team tasks
- **api**: Python 3.12 Lambdas behind API Gateway; EventBridge Scheduler for
  the recurring conflict check and reminders
- **hosting**: private S3 bucket behind CloudFront for the dashboard

Secrets (Gemini API key, Google OAuth client + refresh token, Telegram bot
token) live in AWS Secrets Manager, never in this repo.

Model layer is the Google Gemini API. Calendar access is Google Calendar via
OAuth with a stored refresh token.

## Status

Scaffolding. Nothing deployed yet. See BUILD_LOG.md for the honest history.
