
  
    

create or replace transient table PHARMACOVIGILANCE.PUBLIC.silver_reports_aggregated
    
    
    
    as (

WITH drug_events AS (
    SELECT primaryid, standard_concept_id
    FROM PHARMACOVIGILANCE.PUBLIC.stg_bronze_drug
),
outcome_events AS (
    SELECT primaryid, outcome_concept_id
    FROM PHARMACOVIGILANCE.PUBLIC.stg_bronze_outcome
)

SELECT
    de.primaryid,
    de.standard_concept_id AS drug_id,
    ARRAY_AGG(DISTINCT oe.outcome_concept_id) AS reaction_concept_ids
FROM
    drug_events AS de
JOIN
    outcome_events AS oe ON de.primaryid = oe.primaryid
GROUP BY
    de.primaryid, de.standard_concept_id
    )
;


  