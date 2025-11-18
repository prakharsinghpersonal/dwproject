from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator
from datetime import datetime

COPY_DRUG_SQL = """
COPY INTO PHARMACOVIGILANCE.PUBLIC.BRONZE_DRUG
FROM @aeolus_s3_external_stage/standard_case_drug.tsv
ON_ERROR = 'SKIP_FILE';
"""

COPY_OUTCOME_SQL = """
COPY INTO PHARMACOVIGILANCE.PUBLIC.BRONZE_OUTCOME
FROM @aeolus_s3_external_stage/standard_case_outcome.tsv
ON_ERROR = 'SKIP_FILE';
"""

with DAG(
    dag_id='drug_syndrome_pipeline_s3_v1',
    start_date=datetime(2025, 11, 16),
    schedule_interval='@daily',
    catchup=False,
) as dag:
    copy_bronze_drug = SnowflakeOperator(
        task_id='copy_bronze_drug_from_s3',
        sql=COPY_DRUG_SQL,
        snowflake_conn_id='snowflake_default',
    )

    copy_bronze_outcome = SnowflakeOperator(
        task_id='copy_bronze_outcome_from_s3',
        sql=COPY_OUTCOME_SQL,
        snowflake_conn_id='snowflake_default',
    )

    run_dbt_models = BashOperator(
        task_id='run_dbt_models',
        bash_command=(
            "cd /opt/airflow/dbt_project && "
            "dbt run --profiles-dir . --vars '{"
            "\"SNOWFLAKE_USER\":\"{{ var.value.SNOWFLAKE_USER }}\"," 
            "\"SNOWFLAKE_PASSWORD\":\"{{ var.value.SNOWFLAKE_PASSWORD }}\"," 
            "\"SNOWFLAKE_ACCOUNT\":\"{{ var.value.SNOWFLAKE_ACCOUNT }}\"}'"
        ),
        env={
            'SNOWFLAKE_USER': '{{ var.value.SNOWFLAKE_USER }}',
            'SNOWFLAKE_PASSWORD': '{{ var.value.SNOWFLAKE_PASSWORD }}',
            'SNOWFLAKE_ACCOUNT': '{{ var.value.SNOWFLAKE_ACCOUNT }}',
            'SNOWFLAKE_WAREHOUSE': '{{ var.value.SNOWFLAKE_WAREHOUSE }}',
            'SNOWFLAKE_DATABASE': '{{ var.value.SNOWFLAKE_DATABASE }}',
            'SNOWFLAKE_SCHEMA': '{{ var.value.SNOWFLAKE_SCHEMA }}',
        },
    )

    load_to_neo4j = DockerOperator(
        task_id='load_to_neo4j',
        image='neo4j-loader:latest',
        auto_remove=True,
        environment={
            'SNOWFLAKE_USER': '{{ var.value.SNOWFLAKE_USER }}',
            'SNOWFLAKE_PASSWORD': '{{ var.value.SNOWFLAKE_PASSWORD }}',
            'SNOWFLAKE_ACCOUNT': '{{ var.value.SNOWFLAKE_ACCOUNT }}',
            'NEO4J_URI': '{{ var.value.NEO4J_URI }}',
            'NEO4J_PASSWORD': '{{ var.value.NEO4J_PASSWORD }}',
            'NEO4J_USERNAME': 'neo4j',
            'NEO4J_DATABASE': 'neo4j',
        },
    )

    run_final_analysis = DockerOperator(
        task_id='run_final_analysis',
        image='analysis-runner:latest',
        auto_remove=True,
        environment={
            'SNOWFLAKE_USER': '{{ var.value.SNOWFLAKE_USER }}',
            'SNOWFLAKE_PASSWORD': '{{ var.value.SNOWFLAKE_PASSWORD }}',
            'SNOWFLAKE_ACCOUNT': '{{ var.value.SNOWFLAKE_ACCOUNT }}',
        },
    )

    [copy_bronze_drug, copy_bronze_outcome] >> run_dbt_models
    run_dbt_models >> [load_to_neo4j, run_final_analysis]
