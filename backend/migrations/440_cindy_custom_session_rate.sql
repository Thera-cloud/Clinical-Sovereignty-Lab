-- Cindy Joy special live-session rate $100 (operator 2026-09-20).
-- Does not rewrite historically paid sessions. Coach-assigned custom_session_rate_cents
-- is honored for all clients via quote_session_price_cents.

UPDATE users
   SET profile_data = jsonb_set(
           jsonb_set(
               jsonb_set(
                   COALESCE(profile_data, '{}'::jsonb),
                   '{custom_session_rate_cents}',
                   '10000'::jsonb
               ),
               '{custom_session_rate_note}',
               '"special rate agreement"'::jsonb
           ),
           '{custom_session_rate_set_at}',
           to_jsonb(NOW()::text)
       )
 WHERE username = 'cindyjoy' AND role = 'CLIENT';

UPDATE coaching_sessions cs
   SET price_cents = 10000,
       session_data = COALESCE(cs.session_data, '{}'::jsonb)
         || jsonb_build_object(
              'price_cents', 10000,
              'custom_rate', true,
              'coach_fee', 100.0
            ),
       updated_at = NOW()
  FROM users u
 WHERE u.username = 'cindyjoy' AND u.role = 'CLIENT'
   AND cs.payment_status = 'pending'
   AND COALESCE(cs.stripe_payment_intent_id, '') = ''
   AND COALESCE(cs.session_data->>'stripe_invoice_id', '') = ''
   AND UPPER(COALESCE(cs.status, '')) IN (
         'SCHEDULED', 'CONFIRMED', 'ACTIVE', 'PENDING_APPROVAL')
   AND (cs.client_id::text = u.hardware_id
        OR cs.client_id::text = u.username
        OR cs.client_id::text = u.id::text);
