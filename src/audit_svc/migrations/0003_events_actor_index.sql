-- индекс для выборки событий по пользователю
CREATE INDEX IF NOT EXISTS events_actor_idx ON events (actor);
