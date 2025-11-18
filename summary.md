# Adverse Event Pipeline - Project Summary

## Overview
- End-to-end pharmacovigilance pipeline ingesting FAERS (AEOLUS) data (30M drug rows, 31M outcome rows)
- Technologies: Snowflake, dbt, Docker, Airflow, Neo4j, pandas/scipy, Streamlit
- Architecture: Bronze/Silver/Gold dbt layers, Docker containers for analysis & Neo4j loader, optional Airflow DAG, standalone `run_pipeline.py`

## Data & Transformations
- Bronze tables: `BRONZE_DRUG`, `BRONZE_OUTCOME`
- dbt staging: `stg_bronze_drug`, `stg_bronze_outcome` (includes case-insensitive noise filter)
- Silver: `silver_reports_aggregated` (per-report arrays for drug & reaction concept IDs)
- Gold: `gold_contingency_table` (now per-drug universal co-occurrence statistics with `drug_id`, `N11/10/01/00`) and `gold_reaction_dictionary`

## Analysis Pipeline
- Dockerized `analysis-runner` loads Gold data, filters injection-site noise, builds NetworkX graph, Louvain communities, Fisher's exact test
- Outputs: `statistical_analysis.csv` (includes `drug_id`, `reaction_*`, co-occurrence, odds ratio, p-value, significance) and `reaction_communities.csv`
- Dockerized `neo4j-loader` loads Silver aggregate into Neo4j Aura (safe clear, batch inserts, `driver.verify_connectivity`)
- `run_pipeline.py` orchestrates dbt-runner, loader, analysis containers and copies CSVs locally

## Orchestration
- Airflow DAG (`pharmacovigilance_dag.py`): Snowflake COPY from S3, dbt task, Neo4j loader & analysis DockerOperators (now optional; pipeline can be run via script)
- Docker Compose for Airflow installs Snowflake, dbt-cloud, Docker providers, mounts dbt project, sets Fernet key and admin credentials

## Dashboard
- Streamlit app (`dashboard.py`) loads CSVs, merges reaction dictionary, now includes dropdown to select any drug ID (27 unique in current run)
- Displays top significant syndrome pairs, odds ratio chart, community summary

## Credentials & Env
- `.env` stores Snowflake & Neo4j secrets; `profiles.yml` and containers read via env vars

## Key Results (latest run)
- `gold_contingency_table`: universal multi-drug co-occurrence stats with `drug_id`
- `statistical_analysis.csv`: 100 top non-injection-site pairs, 27 drugs (sample: 1119119, 1151789, 40103241)
- Communities: reaction_communities.csv (518 lines) with Louvain clusters
- Dashboard now shows dropdown for drug IDs and filtered results

## Verification Steps Completed
1. dbt run (2025-11-17) > Gold tables rebuilt with `drug_id`
2. Pipeline script executed: dbt models, Neo4j loader, Analysis runner (CSV copied locally)
3. Verified CSV structure (columns: `drug_id`, `reaction_1`, ...)
4. Streamlit restarted; dropdown available

## How to Reproduce
```bash
# 1. Ensure .env loaded
source .env

# 2. Run dbt
cd dbt_project && dbt run

# 3. Run pipeline/script
cd .. && python run_pipeline.py

# 4. Launch dashboard
streamlit run dashboard.py
```

## Open Items / Notes
- Airflow DAG optional; script path used for demos
- Neo4j load limited to 20k reports to respect Aura Free tier relationship cap
- Streamlit dictionary requires latest CSVs; fallback to Snowflake fetch available
