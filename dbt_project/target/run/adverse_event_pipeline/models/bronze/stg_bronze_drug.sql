
  create or replace   view PHARMACOVIGILANCE.PUBLIC.stg_bronze_drug
  
  
  
  
  as (
    

SELECT
    primaryid,
    standard_concept_id,
    drug_seq,
    role_cod
FROM PHARMACOVIGILANCE.PUBLIC.BRONZE_DRUG
WHERE standard_concept_id IS NOT NULL
  );

