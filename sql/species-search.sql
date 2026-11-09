SELECT          im.Name AS "Image",
                im.Date AS "Date",
                COUNT(i.Id) AS "Identifications"
FROM            IDENTIFICATION i
INNER JOIN      IMAGE im ON im.Id = i.ImageId
INNER JOIN      SPECIES sp ON sp.Id = i.SpeciesId
WHERE           sp.CommonName = 'Moorish Idol'
GROUP BY        im.Id,
                im.Name,
                im.Date
ORDER BY        im.Date ASC,
                im.Name ASC;