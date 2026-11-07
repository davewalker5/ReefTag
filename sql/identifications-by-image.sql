SELECT      im.Name AS "Image",
            im.Date AS "Date",
            COUNT( i.Id ) AS "Identifications"
FROM        IDENTIFICATION i
INNER JOIN  IMAGE im ON im.Id = i.ImageId
GROUP BY    im.Name, im.Date
ORDER BY    COUNT( i.Id ) DESC;
