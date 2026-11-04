CREATE TABLE IF NOT EXISTS goal_history (
 event_id TEXT PRIMARY KEY,
 effective_date TEXT,
 known_before_date TEXT,
 phase TEXT NOT NULL,
 calories REAL NOT NULL CHECK (calories BETWEEN 500 AND 10000),
 protein_g REAL CHECK (protein_g BETWEEN 0 AND 500),
 recorded_at TEXT NOT NULL,
 CHECK ((effective_date IS NOT NULL AND known_before_date IS NULL)
     OR (effective_date IS NULL AND known_before_date IS NOT NULL))
);
ALTER TABLE public.goal_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.goal_history FROM PUBLIC, anon, authenticated;
