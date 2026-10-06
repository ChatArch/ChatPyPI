"""Dependency-free, fixed public errors shared by API adapters."""

SAFE_ERROR_MESSAGES = {
    "invalid_request": "Request validation failed.",
    "unsafe_state": "Registration state storage failed a safety check.",
    "service_auth_missing": "Service authentication is not configured.",
    "origin_rejected": "Browser-origin API requests are not accepted.",
    "needs_auth": "Required provider authentication is unavailable or invalid.",
    "preflight_unknown": "A required provider read could not be verified.",
    "target_unavailable": "The requested package or repository target is unavailable.",
    "confirmation_mismatch": "Exact registration target confirmation does not match the plan.",
    "idempotency_conflict": "The idempotency key was already used for another submission.",
    "target_busy": "A registration job already owns this normalized name.",
    "queue_full": "The registration queue is full.",
    "executor_locked": "Another registration executor already owns this state directory.",
    "registration_disabled": "Registration writes are disabled by service configuration.",
    "plan_not_found": "Registration plan was not found.",
    "job_not_found": "Registration job was not found.",
    "local_execution": "Local package preparation failed.",
    "external_outcome_unknown": "An external write outcome is unknown and requires reconciliation.",
    "interrupted": "The job was interrupted and requires reconciliation before any retry.",
}

ERROR_STATUS_CODES = {
    "invalid_request": 400, "unsafe_state": 500, "service_auth_missing": 500,
    "origin_rejected": 403, "needs_auth": 409, "preflight_unknown": 409,
    "target_unavailable": 409, "confirmation_mismatch": 409,
    "idempotency_conflict": 409, "target_busy": 409, "queue_full": 429,
    "executor_locked": 503, "registration_disabled": 403, "plan_not_found": 404,
    "job_not_found": 404, "local_execution": 500,
    "external_outcome_unknown": 409, "interrupted": 409,
}
