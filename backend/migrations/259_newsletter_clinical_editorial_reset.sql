-- Migration 259: Reset Dispatch content for clinical psychoeducation editorial.
-- Clears issues (all statuses), trend candidates, and forecast; re-seeds clinical curriculum.
-- Subscribers / consent preserved.

BEGIN;

-- Child tables cascade from newsletter_issues (citations, sends, feedback, library_stats).
DELETE FROM newsletter_issues;

TRUNCATE TABLE newsletter_trend_candidates RESTART IDENTITY;

DELETE FROM newsletter_topic_forecast;

DELETE FROM newsletter_topic_memory;

DELETE FROM newsletter_chat_signals;

-- Optional: clear growth ledger tied to wiped library (fresh attribution)
DELETE FROM newsletter_growth_ledger;

-- Seed clinical curriculum forecast rows (idempotent keys)
INSERT INTO newsletter_topic_forecast
    (topic_key, seasonal_label, target_week, news_velocity, foresight_score, metadata)
VALUES
    ('cbt_thought_records', 'Clinical curriculum', CURRENT_DATE, 0, 0.90,
     '{"domain":"cbt","clinical":true,"title":"CBT thought records: catching the story before it runs you","seed":"clinical_v1"}'::jsonb),
    ('cbt_behavioral_activation', 'Clinical curriculum', CURRENT_DATE + 7, 0, 0.88,
     '{"domain":"cbt","clinical":true,"title":"Behavioral activation: tiny actions that reopen a stuck day","seed":"clinical_v1"}'::jsonb),
    ('dbt_distress_tolerance', 'Clinical curriculum', CURRENT_DATE + 14, 0, 0.89,
     '{"domain":"dbt","clinical":true,"title":"DBT distress tolerance: riding the wave without making it worse","seed":"clinical_v1"}'::jsonb),
    ('dbt_interpersonal_effectiveness', 'Clinical curriculum', CURRENT_DATE + 21, 0, 0.89,
     '{"domain":"dbt","clinical":true,"title":"DBT DEAR MAN: asking clearly without collapsing or attacking","seed":"clinical_v1"}'::jsonb),
    ('act_values_and_defusion', 'Clinical curriculum', CURRENT_DATE + 28, 0, 0.87,
     '{"domain":"act","clinical":true,"title":"ACT: defuse from sticky thoughts and move toward values","seed":"clinical_v1"}'::jsonb),
    ('ifs_parts_mapping', 'Clinical curriculum', CURRENT_DATE + 35, 0, 0.86,
     '{"domain":"ifs","clinical":true,"title":"IFS parts language: meeting protectors without exile-hunting","seed":"clinical_v1"}'::jsonb),
    ('adep_attachment_repair', 'Clinical curriculum', CURRENT_DATE + 42, 0, 0.88,
     '{"domain":"adep","clinical":true,"title":"ADEP / attachment: naming the protest under the fight","seed":"clinical_v1"}'::jsonb),
    ('grounding_5_4_3_2_1', 'Clinical curriculum', CURRENT_DATE + 49, 0, 0.90,
     '{"domain":"somatic","clinical":true,"title":"Grounding 5-4-3-2-1: coming back when the body time-travels","seed":"clinical_v1"}'::jsonb),
    ('polyvagal_window_of_tolerance', 'Clinical curriculum', CURRENT_DATE + 56, 0, 0.87,
     '{"domain":"somatic","clinical":true,"title":"Window of tolerance: noticing hyperarousal, shutdown, and return","seed":"clinical_v1"}'::jsonb),
    ('mi_change_talk', 'Clinical curriculum', CURRENT_DATE + 63, 0, 0.85,
     '{"domain":"mi","clinical":true,"title":"Motivational Interviewing: hearing your own reasons for change","seed":"clinical_v1"}'::jsonb),
    ('relationship_repair_attempts', 'Clinical curriculum', CURRENT_DATE + 70, 0, 0.88,
     '{"domain":"relationships","clinical":true,"title":"Repair attempts: the small bids that stop a fight from becoming a story","seed":"clinical_v1"}'::jsonb),
    ('relationship_listening_reflect', 'Clinical curriculum', CURRENT_DATE + 77, 0, 0.87,
     '{"domain":"relationships","clinical":true,"title":"Reflective listening: hearing the need under the volume","seed":"clinical_v1"}'::jsonb),
    ('nate_usage_skill_coach', 'Clinical curriculum', CURRENT_DATE + 84, 0, 0.91,
     '{"domain":"nate_usage","clinical":true,"title":"How to use Little Nate: ask for skills, not just comfort","seed":"clinical_v1"}'::jsonb),
    ('nate_usage_crisis_boundaries', 'Clinical curriculum', CURRENT_DATE + 91, 0, 0.90,
     '{"domain":"nate_usage","clinical":true,"title":"How to use Little Nate safely: crisis lines stay human","seed":"clinical_v1"}'::jsonb),
    ('shame_self_compassion', 'Clinical curriculum', CURRENT_DATE + 98, 0, 0.86,
     '{"domain":"self_compassion","clinical":true,"title":"Shame vs guilt: self-compassion without letting yourself off the hook","seed":"clinical_v1"}'::jsonb),
    ('anxiety_exposure_ladder', 'Clinical curriculum', CURRENT_DATE + 105, 0, 0.87,
     '{"domain":"cbt","clinical":true,"title":"Anxiety exposure ladder: graded steps instead of white-knuckle leaps","seed":"clinical_v1"}'::jsonb);

COMMIT;
