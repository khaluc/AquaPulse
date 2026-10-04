-- Human-in-the-loop (plan section 16): who reviews a report, and what they decided.

-- 'published': shown as a preliminary result (the "show" branch of section 16).
ALTER TABLE observations DROP CONSTRAINT observations_status_check;
ALTER TABLE observations ADD CONSTRAINT observations_status_check
    CHECK (status IN ('pending', 'published', 'needs_confirmation', 'needs_verification',
                      'verified', 'dismissed'));
ALTER TABLE observations ADD COLUMN review_reasons text[] NOT NULL DEFAULT '{}';
ALTER TABLE observations ADD COLUMN expert_required boolean NOT NULL DEFAULT false;
ALTER TABLE observations ADD COLUMN verified_at timestamptz;

-- One task per report in the queue. open -> claimed -> (escalated ->) resolved.
CREATE TABLE verification_tasks (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    observation_id    uuid NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    status            text NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'claimed', 'escalated', 'resolved')),
    expert_required   boolean NOT NULL,
    reasons           text[] NOT NULL DEFAULT '{}',
    assignee_id       text,
    claimed_at        timestamptz,
    volunteer_id      text,
    volunteer_verdict text CHECK (volunteer_verdict IN ('confirmed', 'not_confirmed', 'unclear')),
    volunteer_note    text,
    submitted_at      timestamptz,
    expert_id         text,
    final_verdict     text CHECK (final_verdict IN ('confirmed', 'not_confirmed')),
    final_note        text,
    resolved_at       timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- At most one unresolved task per report, so re-scoring cannot queue it twice.
CREATE UNIQUE INDEX verification_tasks_one_active ON verification_tasks (observation_id)
    WHERE status <> 'resolved';
CREATE INDEX verification_tasks_status_idx ON verification_tasks (status);

-- Every decision, with who made it: the audit trail for "AI assists, people decide".
CREATE TABLE verification_events (
    id          bigserial PRIMARY KEY,
    task_id     uuid NOT NULL REFERENCES verification_tasks(id) ON DELETE CASCADE,
    actor_id    text NOT NULL,
    role        text NOT NULL CHECK (role IN ('reporter', 'volunteer', 'expert', 'system')),
    action      text NOT NULL,
    note        text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX verification_events_task_idx ON verification_events (task_id);
