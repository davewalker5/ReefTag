SELECT          im.Name AS "Image",
                f.Date AS "Date",
                COUNT(i.Id) AS "Identifications"
FROM            IDENTIFICATION i
INNER JOIN      IMAGE im ON im.Id = i.ImageId
INNER JOIN      FOLDER f ON f.Id = im.FolderId
INNER JOIN      SPECIES sp ON sp.Id = i.SpeciesId
WHERE           sp.CommonName = 'Moorish Idol'
GROUP BY        im.Id,
                im.Name,
                f.Date
ORDER BY        f.Date ASC,
                im.Name ASC;
