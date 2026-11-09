CREATE TABLE Species (
    Id              INTEGER  NOT NULL
                             CONSTRAINT PK_Species PRIMARY KEY AUTOINCREMENT,
    CategoryId      INTEGER  NOT NULL,
    Name            TEXT     NULL,
    Created_By      INTEGER  DEFAULT '0'
                             NOT NULL,
    Updated_By      INTEGER  DEFAULT '0'
                             NOT NULL,
    Date_Created    DATETIME DEFAULT '1994-01-01 00:00:00'
                             NOT NULL,
    Date_Updated    DATETIME DEFAULT '1994-01-01 00:00:00'
                             NOT NULL,
    Scientific_Name TEXT,
    CONSTRAINT FK_Species_Categories_CategoryId FOREIGN KEY (
        CategoryId
    )
    REFERENCES Categories (Id) ON DELETE CASCADE
);

CREATE TABLE Categories (
    Id              INTEGER  NOT NULL
                             CONSTRAINT PK_Categories PRIMARY KEY AUTOINCREMENT,
    Name            TEXT     NULL,
    Created_By      INTEGER  DEFAULT '0'
                             NOT NULL,
    Updated_By      INTEGER  DEFAULT '0'
                             NOT NULL,
    Date_Created    DATETIME DEFAULT '1994-01-01 00:00:00'
                             NOT NULL,
    Date_Updated    DATETIME DEFAULT '1994-01-01 00:00:00'
                             NOT NULL,
    Supports_Gender INTEGER  DEFAULT '1'
                             NOT NULL
);

CREATE TABLE Sightings (
    Id           INTEGER  NOT NULL
                          CONSTRAINT PK_Sightings PRIMARY KEY AUTOINCREMENT,
    LocationId   INTEGER  NOT NULL,
    SpeciesId    INTEGER  NOT NULL,
    Date         TEXT     NOT NULL,
    Number       INTEGER,
    WithYoung    INTEGER  NOT NULL
                          DEFAULT 0,
    Gender       INTEGER  NOT NULL
                          DEFAULT 0,
    Notes        TEXT     NULL,
    Created_By   INTEGER  DEFAULT '0'
                          NOT NULL,
    Updated_By   INTEGER  DEFAULT '0'
                          NOT NULL,
    Date_Created DATETIME DEFAULT '1994-01-01 00:00:00'
                          NOT NULL,
    Date_Updated DATETIME DEFAULT '1994-01-01 00:00:00'
                          NOT NULL,
    CONSTRAINT FK_Sightings_Locations_LocationId FOREIGN KEY (
        LocationId
    )
    REFERENCES Locations (Id) ON DELETE CASCADE,
    CONSTRAINT FK_Sightings_Species_SpeciesId FOREIGN KEY (
        SpeciesId
    )
    REFERENCES Species (Id) ON DELETE CASCADE
);

CREATE TABLE Locations (
    Id           INTEGER  NOT NULL
                          CONSTRAINT PK_Locations PRIMARY KEY AUTOINCREMENT,
    Name         TEXT     NULL,
    Address      TEXT     NULL,
    City         TEXT     NULL,
    Country      TEXT     NULL,
    County       TEXT     NULL,
    Latitude     TEXT     NULL,
    Longitude    TEXT     NULL,
    Postcode     TEXT     NULL,
    Created_By   INTEGER  DEFAULT '0'
                          NOT NULL,
    Updated_By   INTEGER  DEFAULT '0'
                          NOT NULL,
    Date_Created DATETIME DEFAULT '1994-01-01 00:00:00'
                          NOT NULL,
    Date_Updated DATETIME DEFAULT '1994-01-01 00:00:00'
                          NOT NULL
);
