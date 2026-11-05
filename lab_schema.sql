CREATE TABLE IF NOT EXISTS lab_collections (
 collection_id TEXT PRIMARY KEY,
 collected_on TEXT NOT NULL,
 source TEXT NOT NULL,
 performing_lab TEXT,
 fasting INTEGER CHECK (fasting IN (0,1)),
 provenance TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_panels (
 panel_id TEXT PRIMARY KEY,
 collection_id TEXT NOT NULL REFERENCES lab_collections(collection_id),
 panel_name TEXT NOT NULL,
 ordered_on TEXT,
 resulted_on TEXT NOT NULL,
 source_text TEXT NOT NULL,
 notes TEXT
);
CREATE INDEX IF NOT EXISTS lab_panels_collection_idx ON lab_panels(collection_id);
CREATE TABLE IF NOT EXISTS lab_results (
 panel_id TEXT NOT NULL REFERENCES lab_panels(panel_id),
 test_key TEXT NOT NULL,
 test_name TEXT NOT NULL,
 result_text TEXT NOT NULL CHECK (length(result_text)>0),
 value_numeric DOUBLE PRECISION,
 comparator TEXT CHECK (comparator IN ('=','>','>=','<','<=')),
 units_reported TEXT,
 units_display TEXT,
 unit_note TEXT,
 reference_text TEXT,
 reported_flag TEXT,
 display_order INTEGER NOT NULL,
 PRIMARY KEY (panel_id,test_key),
 CHECK ((value_numeric IS NULL AND comparator IS NULL)
     OR (value_numeric IS NOT NULL AND comparator IS NOT NULL))
);

ALTER TABLE public.lab_collections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.lab_collections FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.lab_collections TO service_role;
ALTER TABLE public.lab_panels ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.lab_panels FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.lab_panels TO service_role;
ALTER TABLE public.lab_results ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.lab_results FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.lab_results TO service_role;
