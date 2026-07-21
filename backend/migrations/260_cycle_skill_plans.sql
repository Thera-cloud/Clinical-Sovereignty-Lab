-- QUANTUM-CRYSTAL-ARCH: Cycle-driven short skill plans + stacked follow-ups
-- Extends nate_therapeutic_plans / nate_commitments for chat-path micro-plans.

ALTER TABLE nate_therapeutic_plans
    DROP CONSTRAINT IF EXISTS nate_therapeutic_plans_status_check;

ALTER TABLE nate_therapeutic_plans
    ADD CONSTRAINT nate_therapeutic_plans_status_check
    CHECK (status IN ('suggested', 'active', 'paused', 'completed', 'abandoned'));

ALTER TABLE nate_therapeutic_plans
    ADD COLUMN IF NOT EXISTS source VARCHAR(32) NOT NULL DEFAULT 'coach'
        CHECK (source IN ('coach', 'cycle_skill', 'nate_suggest'));

ALTER TABLE nate_therapeutic_plans
    ADD COLUMN IF NOT EXISTS cycle_domain VARCHAR(64);

ALTER TABLE nate_therapeutic_plans
    ADD COLUMN IF NOT EXISTS parent_plan_id UUID
        REFERENCES nate_therapeutic_plans(id) ON DELETE SET NULL;

ALTER TABLE nate_therapeutic_plans
    ADD COLUMN IF NOT EXISTS modality VARCHAR(16);

ALTER TABLE nate_therapeutic_plans
    ADD COLUMN IF NOT EXISTS next_checkin_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_nate_therapeutic_plans_cycle_domain
    ON nate_therapeutic_plans (user_id, cycle_domain)
    WHERE status IN ('suggested', 'active');

-- Allow cycle-skill follow-up commitments
ALTER TABLE nate_commitments
    DROP CONSTRAINT IF EXISTS nate_commitments_source_check;

ALTER TABLE nate_commitments
    ADD CONSTRAINT nate_commitments_source_check
    CHECK (source IN ('auto_extracted', 'client_entered', 'cycle_skill_plan'));

-- Seed short stacked skill templates (3–4 steps; build on each other via succession)
INSERT INTO plan_templates (id, title, total_steps, step_definitions, created_by)
VALUES
(
    'a1000001-0001-4000-8000-000000000001',
    'Distress skills practice (DBT-informed)',
    4,
    '[
      {"step_number":1,"theme":"Name the wave","skill":"STOP","modality":"DBT",
       "practice":"Ground first (feel feet/seat 10s), then STOP: Stop, Take a step back, Observe, Proceed mindfully — about 90 seconds.",
       "check_in":"Did you catch one urge or spike with feet-on-floor + STOP?"},
      {"step_number":2,"theme":"Body first","skill":"TIPP","modality":"DBT",
       "practice":"One TIPP element (Temperature/Intense exercise/Paced breathing/Paired muscle) for 2 minutes — paced breathing counts as mindful breath.",
       "check_in":"Which TIPP piece felt usable when you were activated?"},
      {"step_number":3,"theme":"Ride without stacking harm","skill":"urge_surf","modality":"DBT",
       "practice":"Urge-surf 90 seconds: notice peak, ride down, no problem-solving yet.",
       "check_in":"Could you ride one urge without acting on the first impulse?"},
      {"step_number":4,"theme":"Tiny opposite action","skill":"opposite_action","modality":"DBT",
       "practice":"Do one opposite action for 5 minutes that moves toward what you care about.",
       "check_in":"What opposite action did you try, and how did your body feel after?"}
    ]'::jsonb,
    'system_cycle_skill'
),
(
    'a1000001-0001-4000-8000-000000000002',
    'Thought check practice (CBT-informed)',
    3,
    '[
      {"step_number":1,"theme":"Catch the automatic thought","skill":"thought_record","modality":"CBT",
       "practice":"30-second ground (name 3 things you see), then write one hot thought + situation in one sentence. No fixing yet.",
       "check_in":"What automatic thought showed up most this week?"},
      {"step_number":2,"theme":"Evidence for and against","skill":"cognitive_restructure","modality":"CBT",
       "practice":"List 2 facts for and 2 against that thought — keep it short.",
       "check_in":"Did any fact soften the thought even 10%?"},
      {"step_number":3,"theme":"Behavioral experiment","skill":"behavioral_activation","modality":"CBT",
       "practice":"Run one 10-minute experiment that tests the thought in real life.",
       "check_in":"What did the experiment show vs what the thought predicted?"}
    ]'::jsonb,
    'system_cycle_skill'
),
(
    'a1000001-0001-4000-8000-000000000003',
    'Values action practice (ACT-informed)',
    3,
    '[
      {"step_number":1,"theme":"Defuse the sticky thought","skill":"defusion","modality":"ACT",
       "practice":"Three mindful breaths, then label: \"I notice I am having the thought that…\" — say it once or write it.",
       "check_in":"Which sticky thought did you defuse this week?"},
      {"step_number":2,"theme":"Name a value","skill":"values","modality":"ACT",
       "practice":"Name one value under the struggle (e.g. care, honesty, steadiness).",
       "check_in":"What value feels most alive right now?"},
      {"step_number":3,"theme":"One valued next action","skill":"committed_action","modality":"ACT",
       "practice":"Take one 10-minute action toward that value even if the feeling stays.",
       "check_in":"What valued action did you take, and what showed up in your body?"}
    ]'::jsonb,
    'system_cycle_skill'
),
(
    'a1000001-0001-4000-8000-000000000004',
    'Clear ask practice (DBT interpersonal)',
    3,
    '[
      {"step_number":1,"theme":"Describe without blame","skill":"DEAR_MAN_D","modality":"DBT",
       "practice":"Write one Describe sentence: facts only, no judgment words.",
       "check_in":"Could you state the ask as facts first?"},
      {"step_number":2,"theme":"Express + Assert","skill":"DEAR_MAN_EA","modality":"DBT",
       "practice":"Add Express (feeling) + Assert (clear ask) in two short lines.",
       "check_in":"Did you make a clear ask without collapsing or attacking?"},
      {"step_number":3,"theme":"Reinforce + Mindful","skill":"DEAR_MAN_RM","modality":"DBT",
       "practice":"Role-play once: Reinforce why yes helps, stay Mindful if they push back.",
       "check_in":"How did you stay on the ask when you got resistance?"}
    ]'::jsonb,
    'system_cycle_skill'
),
(
    'a1000001-0001-4000-8000-000000000005',
    'Grounding and mindful presence',
    4,
    '[
      {"step_number":1,"theme":"Orient to now","skill":"5_4_3_2_1","modality":"grounding",
       "practice":"5-4-3-2-1: name 5 things you see, 4 you feel/touch, 3 you hear, 2 you smell, 1 you taste (or one steady breath).",
       "check_in":"Did 5-4-3-2-1 bring you even 10% more into the room?"},
      {"step_number":2,"theme":"Body anchor","skill":"feet_seat_breath","modality":"grounding",
       "practice":"Feel feet on floor + sit bones for 20 seconds, then 4 slow breaths (in 4 / out 6).",
       "check_in":"Could you find feet/seat and lengthen the exhale once when activated?"},
      {"step_number":3,"theme":"Mindful noticing","skill":"mindful_observe","modality":"mindfulness",
       "practice":"2-minute observe: watch thoughts/feelings like weather — label \"thinking\" or \"feeling\" without fixing.",
       "check_in":"What did you notice when you watched without fixing for two minutes?"},
      {"step_number":4,"theme":"Mindful return","skill":"mindful_return","modality":"mindfulness",
       "practice":"When pulled into spiral: name one sense (\"hearing the fan\"), one breath, then choose one next kind action.",
       "check_in":"Did naming one sense help you return before the spiral ran the show?"}
    ]'::jsonb,
    'system_cycle_skill'
)
ON CONFLICT (id) DO NOTHING;

COMMENT ON COLUMN nate_therapeutic_plans.source IS
    'coach | cycle_skill | nate_suggest — origin of the plan arc.';
COMMENT ON COLUMN nate_therapeutic_plans.parent_plan_id IS
    'Prior completed/suggested plan this arc builds on (stacking).';
