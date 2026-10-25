CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    app         TEXT        NOT NULL,
    action      TEXT        NOT NULL,
    actor       TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb
);
