-- QUANTUM-CRYSTAL-ARCH: De-bias cycle skill template step 1 practices.
-- Lead with the named CBT/DBT/ACT/DEAR skill (not grounding attractors).
-- Grounding template unchanged for steps that are intentionally sensory.

BEGIN;

-- DBT distress: STOP first (micro-orient optional, not the lesson)
UPDATE plan_templates
SET step_definitions = '[
  {"step_number":1,"theme":"Name the wave","skill":"STOP","modality":"DBT",
   "practice":"STOP skill (~90s): Stop. Take a step back. Observe body/urge without acting. Proceed mindfully with one next kind choice. (Optional: feel seat 5s first if flooded.)",
   "check_in":"Did STOP create even 10 seconds of space?"},
  {"step_number":2,"theme":"Body first","skill":"TIPP","modality":"DBT",
   "practice":"One TIPP element (Temperature / Intense exercise / Paced breathing / Paired muscle) for 2 minutes — paced breathing counts.",
   "check_in":"Which TIPP element did you use?"},
  {"step_number":3,"theme":"Ride without stacking harm","skill":"urge_surf","modality":"DBT",
   "practice":"Urge-surf 90 seconds: notice the urge peak, ride it down, no problem-solving yet.",
   "check_in":"Did the urge peak and fall without you stacking harm?"},
  {"step_number":4,"theme":"Tiny opposite action","skill":"opposite_action","modality":"DBT",
   "practice":"Do one opposite action for 5 minutes that moves toward what you care about.",
   "check_in":"What opposite action did you take?"}
]'::jsonb
WHERE id = 'a1000001-0001-4000-8000-000000000001';

-- CBT: hot thought first
UPDATE plan_templates
SET step_definitions = '[
  {"step_number":1,"theme":"Catch the automatic thought","skill":"thought_record","modality":"CBT",
   "practice":"Catch one hot thought: write situation + the automatic thought in one sentence. No fixing yet. (If flooded: name 3 things you see for 10s, then write the thought.)",
   "check_in":"What was the hot thought you caught?"},
  {"step_number":2,"theme":"Evidence for and against","skill":"cognitive_restructure","modality":"CBT",
   "practice":"List 2 facts for and 2 against that thought — keep it short.",
   "check_in":"Which evidence surprised you?"},
  {"step_number":3,"theme":"Behavioral experiment","skill":"behavioral_activation","modality":"CBT",
   "practice":"Run one 10-minute experiment that tests the thought in real life.",
   "check_in":"What did the experiment show?"}
]'::jsonb
WHERE id = 'a1000001-0001-4000-8000-000000000002';

-- ACT: defusion first
UPDATE plan_templates
SET step_definitions = '[
  {"step_number":1,"theme":"Defuse the sticky thought","skill":"defusion","modality":"ACT",
   "practice":"Defusion: take three breaths, then say or write once — \"I notice I am having the thought that…\" and finish the sentence. Do not argue with the thought.",
   "check_in":"Could you label the thought without buying it?"},
  {"step_number":2,"theme":"Name a value","skill":"values","modality":"ACT",
   "practice":"Name one value under the struggle (e.g. care, honesty, steadiness).",
   "check_in":"Which value did you name?"},
  {"step_number":3,"theme":"One valued next action","skill":"committed_action","modality":"ACT",
   "practice":"Take one 10-minute action toward that value even if the feeling stays.",
   "check_in":"What valued action did you take?"}
]'::jsonb
WHERE id = 'a1000001-0001-4000-8000-000000000003';

-- DEAR MAN: Describe first
UPDATE plan_templates
SET step_definitions = '[
  {"step_number":1,"theme":"Describe without blame","skill":"DEAR_MAN_D","modality":"DBT",
   "practice":"DEAR MAN — Describe: write one facts-only sentence about the situation (no judgment words, no mind-reading).",
   "check_in":"Was your Describe sentence free of blame words?"},
  {"step_number":2,"theme":"Express + Assert","skill":"DEAR_MAN_EA","modality":"DBT",
   "practice":"Add Express (feeling) + Assert (clear ask) in two short lines.",
   "check_in":"Was your ask clear enough to answer yes/no?"},
  {"step_number":3,"theme":"Reinforce + Mindful","skill":"DEAR_MAN_RM","modality":"DBT",
   "practice":"Role-play once: Reinforce why yes helps, stay Mindful if they push back.",
   "check_in":"Did you stay on your ask without escalating?"}
]'::jsonb
WHERE id = 'a1000001-0001-4000-8000-000000000004';

COMMIT;
