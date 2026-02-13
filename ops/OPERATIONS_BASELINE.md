# Operations Baseline (Production)

## Objective
Define a lightweight, single-operator baseline for monitoring and incident response.

## Health Signals
1. API liveness:
  - `GET /health/live` should return `{"status":"ok"}`.
2. API readiness:
  - `GET /health/ready` should return `{"status":"ready"}`.
3. Worker processing:
  - Worker logs should show active queue consumption and no sustained crash loop.
4. Queue and failure metrics:
  - `GET /health/metrics` (auth required) should be checked for:
    - `queue_depth.default_queue`
    - `queue_depth.dead_letter_queue`
    - `failure_counters.retry_scheduled`
    - `failure_counters.moved_to_dlq`
    - `failure_counters.alert_triggered`

## Alert Thresholds
- Immediate attention:
  - `/health/ready` != 200 for more than 5 minutes.
  - `dead_letter_queue` depth > 0 and increasing.
  - `moved_to_dlq` increases continuously over 15 minutes.
  - API 5xx sustained for core endpoints (`capture`, `query`, `sync`).
  - Host RAM sustained >85% for more than 10 minutes.
  - Any container repeatedly killed/restarted due to OOM.
- Warning:
  - `retry_scheduled` spikes but stabilizes within 15 minutes.
  - queue depth rises temporarily during batch sync windows.
  - Host RAM sustained >75% outside deploy windows.

## Alert Channels
- Minimum:
  - Coolify deployment/failure notifications.
  - Operator notification channel (Telegram/Slack/email).
- Recommended:
  - Daily summary entry in `comms/log.md`.

## Daily Operator Checklist
1. Check `/health/live` and `/health/ready`.
2. Check `/health/metrics` and verify no DLQ growth.
3. Confirm worker service is running.
4. Spot-check one query response quality.
5. If Todoist enabled, spot-check `/v1/sync/todoist/status`.
6. Check host memory and restart counters in Coolify.

## Weekly Operator Checklist
1. Confirm backups were created in the expected schedule.
   - If using R2, verify latest object in `R2_PREFIX/<project>/<env>/` per `ops/R2_BACKUP_RUNBOOK.md`.
2. Test one restore dry-run step from `ops/RESTORE_RUNBOOK.md` (non-destructive).
3. Review deprecation/error logs for new runtime drift.
4. Review token/cost endpoint:
  - `GET /health/costs/daily`
5. Validate Telegram link flow (if enabled).
6. Prune unused Docker images/layers on host.

## Small VPS Runtime Defaults
- API should run with a single process by default:
  - `UVICORN_WORKERS=1`
- Keep deploy-time memory headroom:
  - baseline target ~60-75% RAM usage
  - sustained >85% should trigger remediation
- Swap should remain enabled on low-cost VPS tiers.

## Incident First Actions
1. Identify scope:
  - API down, worker down, DB/Redis unreachable, provider outage, or sync outage.
2. Freeze risky writes if data integrity is in question.
3. Capture evidence:
  - timestamps, job IDs, request IDs, failing endpoints, latest logs.
4. Execute rollback or restore path per:
  - `ops/DEPLOY_CHECKLIST.md`
  - `ops/RESTORE_RUNBOOK.md`
5. Log incident timeline and decision in `comms/log.md`.

## Baseline Evidence Log Template
- Timestamp (UTC): `________________`
- Operator: `________________`
- Health checks status: `pass / fail`
- Queue status summary: `________________`
- DLQ status: `________________`
- Action taken (if any): `________________`
