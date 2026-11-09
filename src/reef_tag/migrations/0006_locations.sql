-- depends: 0005_folder_defaults
CREATE TABLE LOCATION (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    Region TEXT NOT NULL,
    Country TEXT NOT NULL,
    Latitude DECIMAL,
    Longitude DECIMAL
);
