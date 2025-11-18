

WITH drug_report_counts AS (
    SELECT drug_id, COUNT(DISTINCT primaryid) AS n_total_reports
    FROM PHARMACOVIGILANCE.PUBLIC.silver_reports_aggregated
    GROUP BY 1
),
reaction_pairs AS (
    SELECT
        s.primaryid,
        s.drug_id,
        r1.value::INT AS reaction_1,
        r2.value::INT AS reaction_2
    FROM PHARMACOVIGILANCE.PUBLIC.silver_reports_aggregated AS s,
        LATERAL FLATTEN(input => s.reaction_concept_ids) AS r1,
        LATERAL FLATTEN(input => s.reaction_concept_ids) AS r2
    WHERE r1.value < r2.value
),
co_occurrence_counts AS (
    SELECT
        drug_id,
        reaction_1,
        reaction_2,
        COUNT(DISTINCT primaryid) AS n11
    FROM reaction_pairs
    GROUP BY 1,2,3
    HAVING n11 >= 5
),
individual_counts AS (
    SELECT
        s.drug_id,
        r.value::INT AS reaction_id,
        COUNT(DISTINCT s.primaryid) AS n_individual_reports
    FROM PHARMACOVIGILANCE.PUBLIC.silver_reports_aggregated AS s,
        LATERAL FLATTEN(input => s.reaction_concept_ids) AS r
    GROUP BY 1,2
)
SELECT
    coc.drug_id,
    coc.reaction_1,
    coc.reaction_2,
    coc.n11 AS n11,
    ic1.n_individual_reports - coc.n11 AS n10,
    ic2.n_individual_reports - coc.n11 AS n01,
    drc.n_total_reports - (coc.n11 + (ic1.n_individual_reports - coc.n11) + (ic2.n_individual_reports - coc.n11)) AS n00
FROM co_occurrence_counts AS coc
JOIN individual_counts AS ic1 ON coc.drug_id = ic1.drug_id AND coc.reaction_1 = ic1.reaction_id
JOIN individual_counts AS ic2 ON coc.drug_id = ic2.drug_id AND coc.reaction_2 = ic2.reaction_id
JOIN drug_report_counts AS drc ON coc.drug_id = drc.drug_id