-- depends: 0004_species_categories
CREATE TABLE FOLDER (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Path TEXT NOT NULL UNIQUE,
    Date TIMESTAMP NOT NULL
);
-- Preserve original path spelling while recognising both filesystem separators.
CREATE TEMP TABLE image_folders AS
SELECT *, LENGTH(RTRIM(REPLACE(Name, char(92), '/'),
                         REPLACE(REPLACE(Name, char(92), '/'), '/', ''))) AS Separator
FROM IMAGE;
INSERT INTO FOLDER (Path, Date)
SELECT CASE WHEN Separator=0 THEN '' ELSE SUBSTR(Name, 1, MAX(1, Separator-1)) END,
       Date
FROM image_folders
GROUP BY CASE WHEN Separator=0 THEN '' ELSE SUBSTR(Name, 1, MAX(1, Separator-1)) END
HAVING id=MIN(id);
CREATE TABLE new_image (
    id INTEGER PRIMARY KEY,
    Name TEXT NOT NULL,
    Date TEXT NOT NULL,
    FurtherExamination INTEGER NOT NULL DEFAULT 0 CHECK (FurtherExamination IN (0, 1)),
    FolderId INTEGER NOT NULL REFERENCES FOLDER(Id),
    UNIQUE (FolderId, Name)
);
INSERT INTO new_image
SELECT im.id, SUBSTR(im.Name, im.Separator+1), im.Date, im.FurtherExamination, f.Id
FROM image_folders im JOIN FOLDER f ON f.Path=
    CASE WHEN im.Separator=0 THEN '' ELSE SUBSTR(im.Name, 1, MAX(1, im.Separator-1)) END;
DROP TABLE image_folders;
CREATE TEMP TABLE saved_identifications AS SELECT * FROM IDENTIFICATION;
CREATE TEMP TABLE saved_pending AS SELECT * FROM PENDING_IDENTIFICATION;
DROP TABLE IDENTIFICATION;
DROP TABLE PENDING_IDENTIFICATION;
DROP TABLE IMAGE;
ALTER TABLE new_image RENAME TO IMAGE;
CREATE TABLE IDENTIFICATION (
    id INTEGER PRIMARY KEY,
    ImageId INTEGER NOT NULL REFERENCES IMAGE(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    SpeciesId INTEGER NOT NULL REFERENCES SPECIES(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    Number INTEGER NOT NULL CHECK (Number > 0),
    X INTEGER NOT NULL CHECK (X >= 0),
    Y INTEGER NOT NULL CHECK (Y >= 0),
    UNIQUE (ImageId, Number)
);

CREATE INDEX idx_identification_image ON IDENTIFICATION(ImageId);
CREATE INDEX idx_identification_species ON IDENTIFICATION(SpeciesId);

CREATE TABLE PENDING_IDENTIFICATION (
    id INTEGER PRIMARY KEY,
    ImageId INTEGER NOT NULL REFERENCES IMAGE(id),
    X INTEGER NOT NULL CHECK (X >= 0),
    Y INTEGER NOT NULL CHECK (Y >= 0)
);
CREATE INDEX pending_identification_image ON PENDING_IDENTIFICATION(ImageId);

INSERT INTO IDENTIFICATION SELECT * FROM saved_identifications;
INSERT INTO PENDING_IDENTIFICATION SELECT * FROM saved_pending;
DROP TABLE saved_identifications;
DROP TABLE saved_pending;
