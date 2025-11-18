{{ config(materialized='view') }}

{% set EXCLUDED_TERMS = [
    'DEVICE MALFUNCTION',
    'INCORRECT DOSE ADMINISTERED',
    'PRODUCT QUALITY ISSUE',
    'ADMINISTRATION ERROR',
    'DRUG INTOLERANCE'
] %}

SELECT
    primaryid,
    outcome_concept_id,
    PT AS REACTION_NAME
FROM
    {{ source('public', 'BRONZE_OUTCOME') }}
WHERE
    outcome_concept_id IS NOT NULL
    AND PT IS NOT NULL
    AND UPPER(PT) NOT IN ('{{ EXCLUDED_TERMS | join("', '") }}')
