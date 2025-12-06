from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator
from datetime import datetime
import sys
import os
import importlib.util

# Get the directory where this DAG file is located
dag_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, dag_dir)

# Import the task functions using importlib for better compatibility
def import_task_module(module_name):
    """Import a module from the same directory as this DAG file."""
    module_path = os.path.join(dag_dir, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Import task modules
run_dbt_task_module = import_task_module("run_dbt_task")
run_neo4j_task_module = import_task_module("run_neo4j_task")
run_analysis_task_module = import_task_module("run_analysis_task")

# Get the functions
run_dbt_models = run_dbt_task_module.run_dbt_models
load_to_neo4j = run_neo4j_task_module.load_to_neo4j
run_final_analysis = run_analysis_task_module.run_final_analysis

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

    run_dbt_models_task = PythonOperator(
        task_id='run_dbt_models',
        python_callable=run_dbt_models,
    )

    load_to_neo4j_task = PythonOperator(
        task_id='load_to_neo4j',
        python_callable=load_to_neo4j,
    )

    run_final_analysis_task = PythonOperator(
        task_id='run_final_analysis',
        python_callable=run_final_analysis,
    )

    [copy_bronze_drug, copy_bronze_outcome] >> run_dbt_models_task
    run_dbt_models_task >> [load_to_neo4j_task, run_final_analysis_task]
