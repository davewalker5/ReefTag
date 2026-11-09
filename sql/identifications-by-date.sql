SELECT DISTINCT f.Date AS "Date",
                sp.CommonName AS "Species",
                sp.ScientificName AS "Scientific Name"
FROM            IDENTIFICATION i
INNER JOIN      IMAGE im ON im.Id = i.ImageId
INNER JOIN      FOLDER f ON f.Id = im.FolderId
INNER JOIN      SPECIES sp ON sp.Id = i.SpeciesId
ORDER BY        f.Date ASC,
                sp.CommonName ASC;
