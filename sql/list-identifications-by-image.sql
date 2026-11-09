SELECT DISTINCT RTRIM(f.Path, '/') || '/' || im.Name AS "Image",
                sp.CommonName AS "Species",
                sp.ScientificName AS "Scientific Name",
                f.Date AS "Date"
FROM            IDENTIFICATION i
INNER JOIN      IMAGE im ON im.Id = i.ImageId
INNER JOIN      FOLDER f ON f.Id = im.FolderId
INNER JOIN      SPECIES sp ON sp.Id = i.SpeciesId
ORDER BY        f.Date ASC,
                im.Name ASC,
                sp.CommonName ASC;
