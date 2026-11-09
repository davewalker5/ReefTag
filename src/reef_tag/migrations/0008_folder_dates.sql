-- depends: 0007_folder_locations
-- Folder dates are authoritative from this release onward.
ALTER TABLE IMAGE DROP COLUMN Date;
