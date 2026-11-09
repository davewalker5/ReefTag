SELECT      RTRIM(f.Path, '/') || '/' || im.Name AS "Image",
            f.Date AS "Date",
            COUNT( i.Id ) AS "Identifications"
FROM        IDENTIFICATION i
INNER JOIN  IMAGE im ON im.Id = i.ImageId
INNER JOIN  FOLDER f ON f.Id = im.FolderId
GROUP BY    im.Id, f.Path, im.Name, f.Date
ORDER BY    COUNT( i.Id ) DESC;
