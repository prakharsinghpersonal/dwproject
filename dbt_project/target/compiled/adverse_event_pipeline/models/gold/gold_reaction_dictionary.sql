

WITH relevant_reaction_ids AS (
    -- Get all reaction IDs from your final table
    SELECT REACTION_1 AS concept_id FROM PHARMACOVIGILANCE.PUBLIC.gold_contingency_table
    UNION
    SELECT REACTION_2 AS concept_id FROM PHARMACOVIGILANCE.PUBLIC.gold_contingency_table
)
-- Creates a "dictionary" for your reaction names
SELECT DISTINCT
    src.outcome_concept_id,
    src.pt AS reaction_name
FROM 
    PHARMACOVIGILANCE.PUBLIC.BRONZE_OUTCOME AS src
JOIN
    relevant_reaction_ids AS rel ON src.outcome_concept_id = rel.concept_id