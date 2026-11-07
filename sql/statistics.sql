SELECT  'Excursions'            AS "Metric",
        COUNT( DISTINCT Date )  AS "Count"
FROM    IMAGE
UNION ALL
SELECT  'Images',
        COUNT( Id )
FROM    IMAGE
UNION ALL
SELECT  'Identifications',
        COUNT( Id )
FROM    IDENTIFICATION
UNION ALL
SELECT  'Unknown Markers',
        COUNT( Id )
FROM    PENDING_IDENTIFICATION
UNION ALL
SELECT  'Species',
        COUNT( Id )
FROM    SPECIES
UNION ALL
SELECT  'Identifications per Excursion',
        (
            SELECT COUNT( Id ) * 1.0
            FROM IDENTIFICATION
        ) /
        (
            SELECT COUNT( DISTINCT Date )
            FROM IMAGE
        )
UNION ALL
SELECT  'Identifications per Image',
        (
            SELECT COUNT( Id ) * 1.0
            FROM IDENTIFICATION
        ) /
        (
            SELECT COUNT( Id )
            FROM IMAGE
        )
UNION ALL
SELECT  'Unknown Markers per 100 Identifications',
        (
            SELECT COUNT( Id ) * 1.0
            FROM PENDING_IDENTIFICATION
        ) /
        (
            SELECT COUNT( Id ) / 100.0
            FROM IDENTIFICATION
        );
