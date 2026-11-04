-- depends: 0001_initial_schema
ALTER TABLE IMAGE ADD COLUMN FurtherExamination INTEGER NOT NULL DEFAULT 0
    CHECK (FurtherExamination IN (0, 1));
