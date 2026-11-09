SELECT      SUBSTR(im.Name, INSTR(im.Name, 'GOPR'), 12) AS "Movie",
            im.Date AS "Date",
            COUNT(i.Id) AS "Identifications"
FROM        IDENTIFICATION i
INNER JOIN  IMAGE im ON im.Id = i.ImageId
GROUP BY    SUBSTR(im.Name, INSTR(im.Name, 'GOPR'), 12),
            im.Date
ORDER BY    im.Date ASC,
            "Movie" ASC;
