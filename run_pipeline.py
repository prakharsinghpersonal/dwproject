from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence
import os
import subprocess
import sys



@dataclass(frozen=True)
class Images:
    dbt_runner: str = "dbt-runner:latest"
    neo4j_loader: str = "neo4j-loader:latest"
    analysis_runner: str = "analysis-runner:latest"

@dataclass(frozen=True)
class Paths:
    dbt_project_path: str

@dataclass(frozen=True)
class Containers:
    dbt_name: str = "dbt_run_task"
    loader_name: str = "neo4j_loader_task"
    analysis_name: str = "analysis_task"


# Core static config (mirrors original values)
PATHS = Paths(dbt_project_path=os.path.join(os.getcwd(), "dbt_project"))
IMAGES = Images()
NAMES = Containers()

# Gather environment with original defaults
ENV_VARS: Dict[str, Any] = {
    "SNOWFLAKE_USER": os.getenv("SNOWFLAKE_USER"),
    "SNOWFLAKE_PASSWORD": os.getenv("SNOWFLAKE_PASSWORD"),
    "SNOWFLAKE_ACCOUNT": os.getenv("SNOWFLAKE_ACCOUNT"),
    "SNOWFLAKE_WAREHOUSE": os.getenv("SNOWFLAKE_WAREHOUSE"),
    "SNOWFLAKE_DATABASE": os.getenv("SNOWFLAKE_DATABASE"),
    "SNOWFLAKE_SCHEMA": os.getenv("SNOWFLAKE_SCHEMA"),
    "SNOWFLAKE_ROLE": os.getenv("SNOWFLAKE_ROLE"),
    "NEO4J_URI": os.getenv("NEO4J_URI"),
    "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD"),
    "NEO4J_USERNAME": "neo4j",
    "NEO4J_DATABASE": "neo4j",
}


DBT_RUN_CMD_BASE: List[str] = [
    "docker", "run", "--rm",
    "--network=host",
    "--name", NAMES.dbt_name,
    "-v", f"{PATHS.dbt_project_path}:/dbt_project",
    IMAGES.dbt_runner,
    "run", "--project-dir", "/dbt_project", "--profiles-dir", "/dbt_project",
]

LOADER_RUN_CMD_BASE: List[str] = [
    "docker", "run", "--rm",
    "--network=host",
    "--name", NAMES.loader_name,
    IMAGES.neo4j_loader,
]

ANALYSIS_RUN_CMD_BASE: List[str] = [
    "docker", "run",
    "--network=host",
    "--name", NAMES.analysis_name,
    IMAGES.analysis_runner,
]


def _merge_env() -> Dict[str, str]:
    """
    Merge process env with required variables without altering original behavior.
    Only set non-None values, preserving the original validation elsewhere.
    """
    merged = os.environ.copy()
    for k, v in ENV_VARS.items():
        if v is not None:
            merged[k] = str(v)
    return merged


def build_docker_cmd(base_cmd: Sequence[str], env_vars: Dict[str, Any]) -> List[str]:
    """
    Insert `-e KEY=VALUE` items at the same index as the original (2), so the
    effective docker arg order remains identical.
    """
    cmd = list(base_cmd)
    insert_index = 2  # identical to original placement
    for key, value in env_vars.items():
        if value:
            cmd.insert(insert_index, "-e")
            cmd.insert(insert_index + 1, f"{key}={value}")
            insert_index += 2
    return cmd


def print_stage(title: str) -> None:
    bar = "-" * 3
    print(f"\n{bar} {title} {bar}")


def execute_container(name: str, command: Sequence[str]) -> None:
    """
    Run a docker command. Matches original stdout/stderr behavior and error
    handling (including the Exit 137 OOM note).
    """
    print_stage(f"Running Task: {name}")
    process = subprocess.run(
        list(command),
        env=_merge_env(),
        stdout=sys.stdout,
        stderr=sys.stderr,
        check=False,
    )
    if process.returncode != 0:
        print(f"\n❌ ERROR: {name} failed with exit code {process.returncode}")
        if process.returncode == 137:
            print("   ‼️ FATAL: Analysis Runner was killed (Exit Code 137).")
            print("   ‼️ This is an OUT OF MEMORY error.")
            print("   ‼️ Reduce TOP_PER_DRUG_PAIR_LIMIT in analysis.py and rebuild the image.")
        sys.exit(1)
    print(f"\n✅ SUCCESS: {name} completed.")


def cleanup_container(container_name: str) -> None:
    """
    Force-remove a container if it exists; errors suppressed to mirror original.
    """
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def copy_outputs(container: str, filenames: Iterable[str]) -> None:
    print("\n--- Copying Results from Analysis Container ---")
    try:
        for filename in filenames:
            subprocess.run(
                ["docker", "cp", f"{container}:/app/output/{filename}", "."],
                check=True,
                capture_output=True,
                text=True,
            )
            print(f"✅ Copied {filename}")
    except subprocess.CalledProcessError as exc:
        print(f"⚠️  Warning: Could not copy results: {exc.stderr}")
    finally:
        cleanup_container(container)


def validate_env_or_exit() -> None:
    """
    Enforce the same required-variable rule as the original: all must be set
    except NEO4J_USERNAME and NEO4J_DATABASE which have defaults.
    """
    print("--- Starting Automated Project Execution ---")
    for key, value in ENV_VARS.items():
        if value is None and key not in {"NEO4J_USERNAME", "NEO4J_DATABASE"}:
            print(f'FATAL ERROR: Environment variable {key} is not set. Run "source .env" first.')
            sys.exit(1)


# ╭──────────────────────────────────────────────────────────────────────────────╮
# │ Pipeline                                                                     │
# ╰──────────────────────────────────────────────────────────────────────────────╯
def run_full_pipeline() -> None:
    """
    Execute: dbt → Neo4j loader → analysis → copy outputs. Ordering, names,
    images, volumes, and behavior are preserved.
    """
    dbt_cmd = build_docker_cmd(DBT_RUN_CMD_BASE, ENV_VARS)
    loader_cmd = build_docker_cmd(LOADER_RUN_CMD_BASE, ENV_VARS)
    analysis_cmd = build_docker_cmd(ANALYSIS_RUN_CMD_BASE, ENV_VARS)

    execute_container("dbt Models", dbt_cmd)
    execute_container("Neo4j Loader", loader_cmd)

    cleanup_container(NAMES.analysis_name)
    execute_container("Analysis Runner", analysis_cmd)

    outputs = (
        "statistical_analysis.csv",
        "reaction_communities.csv",
        "gold_reaction_dictionary.csv",
        "gold_drug_dictionary.csv",
        "dashboard_data.csv",
    )
    copy_outputs(NAMES.analysis_name, outputs)

    print("\n#####################################################")
    print("## PIPELINE EXECUTION COMPLETE AND VERIFIED ##")
    print("#####################################################")


if __name__ == "__main__":
    validate_env_or_exit()
    run_full_pipeline()
