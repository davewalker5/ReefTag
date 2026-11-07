SELECT DISTINCT im.Date AS "Date",
                sp.CommonName AS "Species",
                sp.ScientificName AS "Scientific Name"
FROM            IDENTIFICATION i
INNER JOIN      IMAGE im ON im.Id = i.ImageId
INNER JOIN      SPECIES sp ON sp.Id = i.SpeciesId
ORDER BY        im.Date ASC,
                sp.CommonName ASC;
