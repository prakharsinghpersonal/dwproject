{{ config(
    materialized='table'
) }}

-- This query builds the exact structure you need for Neo4j.
-- It joins, groups by report, and collects drugs/reactions into arrays.
SELECT
    t1.primaryid,
    -- Collect a list of unique drug IDs for each report
    ARRAY_AGG(DISTINCT t1.standard_concept_id) AS drug_concept_ids,
    -- Collect a list of unique reaction IDs for each report
    ARRAY_AGG(DISTINCT t2.outcome_concept_id) AS reaction_concept_ids
FROM
    {{ source('public', 'BRONZE_DRUG') }} AS t1
JOIN
    {{ source('public', 'BRONZE_OUTCOME') }} AS t2 ON t1.primaryid = t2.primaryid
WHERE
    t1.standard_concept_id IS NOT NULL
    AND t2.outcome_concept_id IS NOT NULL
GROUP BY
    t1.primaryid
