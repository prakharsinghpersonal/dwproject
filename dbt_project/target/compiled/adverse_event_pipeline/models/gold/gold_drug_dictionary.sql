

-- Since gold_contingency_table is currently for a specific drug (1119119),
-- we'll get all distinct drugs from the staging table
-- TODO: Update this when gold_contingency_table includes drug_id column
SELECT DISTINCT
    standard_concept_id AS drug_id,
    drug_seq,
    role_cod,
    CONCAT('Drug ', standard_concept_id) AS drug_name
FROM PHARMACOVIGILANCE.PUBLIC.stg_bronze_drug
WHERE standard_concept_id IS NOT NULL