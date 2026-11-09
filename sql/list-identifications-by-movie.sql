SELECT DISTINCT SUBSTR(
                    im.Name,
                    INSTR(im.Name, 'GOPR'),
                    12
                ) AS "Movie",
                f.Date AS "Date",
                sp.CommonName AS "Species",
                sp.ScientificName AS "Scientific Name"
FROM            IDENTIFICATION i
INNER JOIN      IMAGE im ON im.Id = i.ImageId
INNER JOIN      FOLDER f ON f.Id = im.FolderId
INNER JOIN      SPECIES sp ON sp.Id = i.SpeciesId
ORDER BY        f.Date ASC,
                im.Name ASC,
                sp.CommonName ASC;
