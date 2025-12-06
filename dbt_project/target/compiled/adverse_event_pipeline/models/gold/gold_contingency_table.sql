

-- ‼️ ACTION: This model uses a 'dbt variable' for the drug ID.
-- You can change '1119119' to a different ID.


WITH reports_with_drug AS (
    -- 1. Get all reports for the target drug
    SELECT DISTINCT 
        primaryid 
    FROM PHARMACOVIGILANCE.PUBLIC.BRONZE_DRUG
    WHERE standard_concept_id = 1119119
),

all_reactions_in_reports AS (
    -- 2. Get all reactions in those reports
    SELECT DISTINCT
        r.primaryid,
        o.outcome_concept_id
    FROM reports_with_drug AS r
    JOIN PHARMACOVIGILANCE.PUBLIC.BRONZE_OUTCOME AS o ON r.primaryid = o.primaryid
    WHERE o.outcome_concept_id IS NOT NULL
),

n_drug AS (
    -- 3. Get total report count for this drug
    SELECT COUNT(*) AS total_reports
    FROM reports_with_drug
),

individual_counts AS (
    -- 4. Get individual reaction counts
    SELECT 
        outcome_concept_id, 
        COUNT(*) AS reaction_count
    FROM all_reactions_in_reports
    GROUP BY 1
),

co_occurrence_pairs AS (
    -- 5. Get co-occurrence counts
    SELECT
        t1.outcome_concept_id AS reaction_1,
        t2.outcome_concept_id AS reaction_2,
        COUNT(DISTINCT t1.primaryid) AS n11 -- N11 = count(reaction 1 AND reaction 2)
    FROM
        all_reactions_in_reports AS t1
    JOIN
        all_reactions_in_reports AS t2 
        ON t1.primaryid = t2.primaryid AND t1.outcome_concept_id < t2.outcome_concept_id
    GROUP BY 1, 2
    HAVING n11 > 5 -- Filter for statistical power
)

-- 6. FINAL TABLE: Build the contingency table
SELECT
    p.reaction_1,
    p.reaction_2,
    p.n11,
    c1.reaction_count - p.n11 AS n10, -- (Count(R1) - Count(R1 and R2))
    c2.reaction_count - p.n11 AS n01, -- (Count(R2) - Count(R1 and R2))
    (SELECT total_reports FROM n_drug) - (p.n11 + (c1.reaction_count - p.n11) + (c2.reaction_count - p.n11)) AS n00
FROM
    co_occurrence_pairs AS p
JOIN
    individual_counts AS c1 ON p.reaction_1 = c1.outcome_concept_id
JOIN
    individual_counts AS c2 ON p.reaction_2 = c2.outcome_concept_id