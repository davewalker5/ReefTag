-- Recreate per-image dates from current folder dates; previous overrides cannot be recovered.
ALTER TABLE IMAGE ADD COLUMN Date TEXT NOT NULL DEFAULT '';
UPDATE IMAGE SET Date = (SELECT SUBSTR(f.Date, 1, 10) FROM FOLDER f WHERE f.Id=IMAGE.FolderId);
