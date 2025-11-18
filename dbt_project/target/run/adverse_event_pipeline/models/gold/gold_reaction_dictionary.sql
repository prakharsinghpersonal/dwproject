
  
    

create or replace transient table PHARMACOVIGILANCE.PUBLIC.gold_reaction_dictionary
    
    
    
    as (



SELECT DISTINCT
    b.outcome_concept_id,
    b.REACTION_NAME
FROM
    PHARMACOVIGILANCE.PUBLIC.stg_bronze_outcome AS b
WHERE
    b.outcome_concept_id IN (
        SELECT reaction_1 FROM PHARMACOVIGILANCE.PUBLIC.gold_contingency_table
        UNION
        SELECT reaction_2 FROM PHARMACOVIGILANCE.PUBLIC.gold_contingency_table
    )
    )
;


  