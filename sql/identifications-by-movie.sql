SELECT      SUBSTR(im.Name, INSTR(im.Name, 'GOPR'), 12) AS "Movie",
            f.Date AS "Date",
            COUNT(i.Id) AS "Identifications"
FROM        IDENTIFICATION i
INNER JOIN  IMAGE im ON im.Id = i.ImageId
INNER JOIN  FOLDER f ON f.Id = im.FolderId
GROUP BY    SUBSTR(im.Name, INSTR(im.Name, 'GOPR'), 12),
            f.Date
ORDER BY    f.Date ASC,
            "Movie" ASC;
