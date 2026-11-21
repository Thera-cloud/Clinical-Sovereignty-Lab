-- Edge wordlist memory. Additive. Source is CF-Connecting-IP, never the Cloudflare peer.

CREATE TABLE IF NOT EXISTS edge_probe_sources (
    source_ip text PRIMARY KEY,
    hit_count integer NOT NULL DEFAULT 0,
    class_count integer NOT NULL DEFAULT 0,
    classes jsonb NOT NULL DEFAULT '[]'::jsonb,
    pattern text,
    mirror_issued boolean NOT NULL DEFAULT false,
    canary_id text,
    namespace_id text,
    canary_seen_at timestamptz,
    first_seen timestamptz NOT NULL DEFAULT now(),
    last_seen timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS edge_probe_events (
    id bigserial PRIMARY KEY,
    source_ip text NOT NULL,
    host text,
    path_class text NOT NULL,
    seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_edge_probe_events_source
    ON edge_probe_events (source_ip, seen_at DESC);
