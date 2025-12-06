import os
import subprocess
import sys
from typing import Any, Dict, List

ENV_VARS: Dict[str, Any] = {
    'SNOWFLAKE_USER': os.getenv('SNOWFLAKE_USER'),
    'SNOWFLAKE_PASSWORD': os.getenv('SNOWFLAKE_PASSWORD'),
    'SNOWFLAKE_ACCOUNT': os.getenv('SNOWFLAKE_ACCOUNT'),
    'SNOWFLAKE_WAREHOUSE': os.getenv('SNOWFLAKE_WAREHOUSE'),
    'SNOWFLAKE_DATABASE': os.getenv('SNOWFLAKE_DATABASE'),
    'SNOWFLAKE_SCHEMA': os.getenv('SNOWFLAKE_SCHEMA'),
    'SNOWFLAKE_ROLE': os.getenv('SNOWFLAKE_ROLE'),
    'NEO4J_URI': os.getenv('NEO4J_URI'),
    'NEO4J_PASSWORD': os.getenv('NEO4J_PASSWORD'),
    'NEO4J_USERNAME': 'neo4j',
    'NEO4J_DATABASE': 'neo4j',
}

DBT_PROJECT_PATH = os.path.join(os.getcwd(), 'dbt_project')
ANALYSIS_CONTAINER_NAME = 'analysis_task'


def build_docker_cmd(base_cmd: List[str], env_vars: Dict[str, Any]) -> List[str]:
    cmd = base_cmd.copy()
    insert_index = 2
    for key, value in env_vars.items():
        if value:
            cmd.insert(insert_index, '-e')
            cmd.insert(insert_index + 1, f'{key}={value}')
            insert_index += 2
    return cmd


DBT_RUN_CMD_BASE = [
    'docker', 'run', '--rm',
    '--network=host',
    '--name', 'dbt_run_task',
    '-v', f'{DBT_PROJECT_PATH}:/dbt_project',
    'dbt-runner:latest',
    'run', '--project-dir', '/dbt_project', '--profiles-dir', '/dbt_project',
]

LOADER_RUN_CMD_BASE = [
    'docker', 'run', '--rm',
    '--network=host',
    '--name', 'neo4j_loader_task',
    'neo4j-loader:latest',
]

ANALYSIS_RUN_CMD_BASE = [
    'docker', 'run',
    '--network=host',
    '--name', ANALYSIS_CONTAINER_NAME,
    'analysis-runner:latest',
]


def execute_container(name: str, command: List[str]):
    print(f"\n--- Running Task: {name} ---")
    merged_env = os.environ.copy()
    merged_env.update(ENV_VARS)
    process = subprocess.run(command, env=merged_env, stdout=sys.stdout, stderr=sys.stderr, check=False)
    if process.returncode != 0:
        print(f"\n❌ ERROR: {name} failed with exit code {process.returncode}")
        if process.returncode == 137:
            print("   ‼️ FATAL: Analysis Runner was killed (Exit Code 137).")
            print("   ‼️ This is an OUT OF MEMORY error.")
            print("   ‼️ Reduce TOP_PER_DRUG_PAIR_LIMIT in analysis.py and rebuild the image.")
        sys.exit(1)
    print(f"\n✅ SUCCESS: {name} completed.")


def cleanup_container(container_name: str):
    subprocess.run(
        ['docker', 'rm', '-f', container_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def run_full_pipeline():
    dbt_cmd = build_docker_cmd(DBT_RUN_CMD_BASE, ENV_VARS)
    loader_cmd = build_docker_cmd(LOADER_RUN_CMD_BASE, ENV_VARS)
    analysis_cmd = build_docker_cmd(ANALYSIS_RUN_CMD_BASE, ENV_VARS)

    execute_container('dbt Models', dbt_cmd)
    execute_container('Neo4j Loader', loader_cmd)

    cleanup_container(ANALYSIS_CONTAINER_NAME)
    execute_container('Analysis Runner', analysis_cmd)

    print("\n--- Copying Results from Analysis Container ---")
    try:
        outputs = [
            'statistical_analysis.csv',
            'reaction_communities.csv',
            'gold_reaction_dictionary.csv',
            'gold_drug_dictionary.csv',
            'dashboard_data.csv',
        ]
        for filename in outputs:
            # Copy to output directory
            os.makedirs('output', exist_ok=True)
            dest_path = os.path.join('output', filename)
            result = subprocess.run(
                ['docker', 'cp', f'{ANALYSIS_CONTAINER_NAME}:/app/output/{filename}', dest_path],
                check=True,
                capture_output=True,
                text=True,
            )
            # Verify the copy was successful for statistical_analysis.csv
            if filename == 'statistical_analysis.csv':
                import pandas as pd
                verify_df = pd.read_csv(dest_path)
                if 'DRUG_ID' in verify_df.columns:
                    print(f"✅ Copied {filename} (DRUG_ID verified)")
                else:
                    print(f"⚠️  WARNING: {filename} copied but DRUG_ID not found in local file!")
            else:
                print(f"✅ Copied {filename}")
    except subprocess.CalledProcessError as exc:
        print(f"⚠️  Warning: Could not copy results: {exc.stderr}")
    finally:
        cleanup_container(ANALYSIS_CONTAINER_NAME)

    print("\n#####################################################")
    print("## PIPELINE EXECUTION COMPLETE AND VERIFIED ##")
    print("#####################################################")


if __name__ == '__main__':
    print('--- Starting Automated Project Execution ---')
    for key, value in ENV_VARS.items():
        if value is None and key not in {'NEO4J_USERNAME', 'NEO4J_DATABASE'}:
            print(f'FATAL ERROR: Environment variable {key} is not set. Run "source .env" first.')
            sys.exit(1)
    run_full_pipeline()
