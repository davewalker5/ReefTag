SELECT      f.Path,
            f.Date,
            COUNT( i.Id ) AS "Images"
FROM        FOLDER f
INNER JOIN  IMAGE i ON i.FolderId = f.Id
GROUP BY    f.Path,
            f.Date
ORDER BY    f.Date ASC, f.Path ASC;
