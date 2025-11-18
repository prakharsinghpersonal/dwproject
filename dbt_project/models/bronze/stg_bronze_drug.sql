{{
  config(
    materialized='view'
  )
}}

SELECT
    primaryid,
    standard_concept_id,
    drug_seq,
    role_cod
FROM {{ source('public', 'BRONZE_DRUG') }}
WHERE standard_concept_id IS NOT NULL
