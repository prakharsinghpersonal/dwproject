
  
    

create or replace transient table PHARMACOVIGILANCE.PUBLIC.gold_drug_dictionary
    
    
    
    as (

SELECT DISTINCT
    standard_concept_id AS drug_id,
    drug_seq,
    role_cod,
    CONCAT('Drug ', standard_concept_id) AS drug_name
FROM PHARMACOVIGILANCE.PUBLIC.stg_bronze_drug
WHERE standard_concept_id IN (
        SELECT DISTINCT drug_id
        FROM PHARMACOVIGILANCE.PUBLIC.gold_contingency_table
    )
    )
;


  