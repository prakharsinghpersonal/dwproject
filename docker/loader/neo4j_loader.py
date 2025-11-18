import json
import os
import sys
import time
from typing import Any, Dict, List

import snowflake.connector
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

BATCH_SIZE = 500
MAX_REPORTS = 20000
SILVER_QUERY = (
    "SELECT primaryid, drug_concept_ids, reaction_concept_ids "
    "FROM SILVER_REPORTS_AGGREGATED "
    f"LIMIT {MAX_REPORTS}"
)


def wake_up_neo4j(driver, retries: int = 5, delay: int = 10) -> bool:
    """Ping Aura until routing is awake."""
    print("--- Verifying Neo4j connection and routing... ---")
    for attempt in range(1, retries + 1):
        try:
            driver.verify_connectivity()
            print("✅ Neo4j is awake and routing is resolved.")
            return True
        except ServiceUnavailable:
            print(f"  Attempt {attempt}/{retries}: Neo4j not ready. Retrying in {delay}s...")
            time.sleep(delay)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"❌ Unexpected error during connectivity check: {exc}")
            return False
    print(f"❌ Failed to verify Neo4j connection after {retries} retries.")
    return False


def _ensure_list(value: Any) -> List[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return [value]


def _write_batch(driver, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    create_graph_query = """
        UNWIND $rows AS row
        MERGE (report:Report {id: row.primaryid})
        FOREACH (drug_id IN row.drug_concept_ids |
            MERGE (drug:Drug {concept_id: drug_id})
            MERGE (report)-[:MENTIONS_DRUG]->(drug)
        )
        FOREACH (reaction_id IN row.reaction_concept_ids |
            MERGE (reaction:Reaction {concept_id: reaction_id})
            MERGE (report)-[:CONTAINS_REACTION]->(reaction)
        )
    """
    # Use the default database for the session if provided by the caller
    # backward-compatible: caller may pass a `database` parameter via kwargs
    db = None
    # If the driver is a neo4j driver that supports named session databases, caller
    # should open the session with database provided in the caller.
    with driver.session() as session:
        session.run(create_graph_query, rows=rows)





def get_snowflake_connection():
    """Create and return a Snowflake connection using environment variables."""
    sf_user = os.environ.get('SNOWFLAKE_USER')
    sf_password = os.environ.get('SNOWFLAKE_PASSWORD')
    sf_account = os.environ.get('SNOWFLAKE_ACCOUNT')
    sf_database = os.environ.get('SNOWFLAKE_DATABASE')
    sf_schema = os.environ.get('SNOWFLAKE_SCHEMA')

    return snowflake.connector.connect(
        user=sf_user,
        password=sf_password,
        account=sf_account,
        database=sf_database,
        schema=sf_schema,
    )


def get_neo4j_driver():
    """Create and return a Neo4j driver and the target database name."""
    neo4j_uri = os.environ.get('NEO4J_URI')
    neo4j_password = os.environ.get('NEO4J_PASSWORD')
    neo4j_database = os.environ.get('NEO4J_DATABASE') or 'neo4j'
    driver = GraphDatabase.driver(neo4j_uri, auth=("neo4j", neo4j_password))
    return driver, neo4j_database


def setup_neo4j_schema(driver, database: str):
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Report) REQUIRE r.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Drug) REQUIRE d.concept_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (rx:Reaction) REQUIRE rx.concept_id IS UNIQUE",
    ]
    with driver.session(database=database) as session:
        for query in constraints:
            session.run(query)
    print("Constraints ensured.")


def fetch_data_from_snowflake(sf_conn) -> List[Dict[str, Any]]:
    """Fetch rows from Snowflake and return a list of records suitable for Neo4j loading.

    Each record will be a dict: { 'report_id': int, 'drugs': [int], 'reactions': [int] }
    """
    print("Fetching data from Snowflake (sample 10k)...")
    query = """
    SELECT
        primaryid,
        ARRAY_TO_STRING(drug_concept_ids, ',') AS drug_ids_str,
        ARRAY_TO_STRING(reaction_concept_ids, ',') AS reaction_ids_str
    FROM
        SILVER_REPORTS_AGGREGATED
    LIMIT 2000;
    """

    cur = sf_conn.cursor(snowflake.connector.DictCursor)
    cur.execute(query)

    records: List[Dict[str, Any]] = []
    while True:
        chunk = cur.fetchmany(BATCH_SIZE)
        if not chunk:
            break
        for r in chunk:
            # Snowflake DictCursor returns uppercase column names
            drug_str = r.get('DRUG_IDS_STR') or ''
            reaction_str = r.get('REACTION_IDS_STR') or ''

            if drug_str.strip() == '':
                drug_ids: List[int] = []
            else:
                drug_ids = [int(x) for x in drug_str.split(',') if x != '']

            if reaction_str.strip() == '':
                reaction_ids: List[int] = []
            else:
                reaction_ids = [int(x) for x in reaction_str.split(',') if x != '']

            records.append({
                'report_id': int(r['PRIMARYID']),
                'drugs': drug_ids,
                'reactions': reaction_ids,
            })

    return records


def load_data_to_neo4j(driver, database: str, records: List[Dict[str, Any]]):
    """
    Loads the data into Neo4j in batches to avoid large single transactions.

    Parameters:
    - driver: Neo4j driver
    - database: target Neo4j database name
    - records: list of records as returned by fetch_data_from_snowflake
    """
    if not records:
        print("No records to load into Neo4j.")
        return

    print("Loading data into Neo4j... This may take a few minutes.")

    # VERY small batch size for safety and to surface errors quickly
    batch_size = 500
    total_records = len(records)

    cypher_query = """
    UNWIND $batch AS row
    MERGE (report:Report {id: row.report_id})

    WITH row, report
    UNWIND row.drugs AS drug_id
    MERGE (drug:Drug {concept_id: drug_id})
    MERGE (report)-[:MENTIONS_DRUG]->(drug)

    WITH row, report
    UNWIND row.reactions AS reaction_id
    MERGE (reaction:Reaction {concept_id: reaction_id})
    MERGE (report)-[:CONTAINS_REACTION]->(reaction)
    """

    # Loop over the records in small batches and handle failures per-batch
    for i in range(0, total_records, batch_size):
        batch = records[i:i + batch_size]
        try:
            with driver.session(database=database) as session:
                # use execute_write for neo4j python-driver v5 to perform write work
                session.execute_write(lambda tx: tx.run(cypher_query, batch=batch))

            print(f"  ... successfully loaded batch {i // batch_size + 1} ({min(i + batch_size, total_records)}/{total_records} reports)")

        except Exception as e:
            # Surface the exact batch-level error and stop further processing
            print(f"❌ FAILED TO LOAD BATCH {i // batch_size + 1}")
            print(f"  ERROR: {e}")
            print("  Stopping data load due to error.")
            break

    print("Data loading loop finished.")


def load_reaction_names(sf_conn, neo4j_driver, database: str):
    """Fetches reaction names from Snowflake and updates nodes in Neo4j."""
    print("Fetching reaction names from Snowflake...")
    cur = sf_conn.cursor(snowflake.connector.DictCursor)
    cur.execute("SELECT OUTCOME_CONCEPT_ID, REACTION_NAME FROM GOLD_REACTION_DICTIONARY;")
    rows = cur.fetchall()

    if not rows:
        print("⚠️ No reaction names found. Did dbt run successfully?")
        return

    # Convert to list of dictionaries with expected keys
    reactions = [
        {"id": int(r["OUTCOME_CONCEPT_ID"]), "name": r.get("REACTION_NAME")}
        for r in rows
    ]

    # Deduplicate by id (Snowflake may return duplicates)
    unique = {}
    for r in reactions:
        unique[r['id']] = r.get('name')
    deduped = [{'id': k, 'name': v} for k, v in unique.items()]

    print(f"Updating {len(deduped)} reaction nodes in Neo4j...")
    cypher_query = """
    UNWIND $records AS reaction
    MATCH (r:Reaction {concept_id: reaction.id})
    SET r.name = reaction.name
    """
    # Run updates in batches to avoid very large single transactions
    batch_size = 2000
    with neo4j_driver.session(database=database) as session:
        for i in range(0, len(deduped), batch_size):
            batch = deduped[i:i+batch_size]
            session.run(cypher_query, records=batch)
    print("✅ Reaction names updated.")


def load_drug_names(sf_conn, neo4j_driver, database: str):
    """Fetches drug names from Snowflake and updates nodes in Neo4j."""
    print("Fetching drug names from Snowflake...")
    cur = sf_conn.cursor(snowflake.connector.DictCursor)
    # Use the actual columns produced by the dbt gold_drug_dictionary model
    cur.execute("SELECT DRUG_ID, DRUG_NAME FROM GOLD_DRUG_DICTIONARY;")
    rows = cur.fetchall()

    if not rows:
        print("⚠️ No drug names found. Did dbt run successfully?")
        return

    drugs = [
        {"id": int(r["DRUG_ID"]), "name": r.get("DRUG_NAME")}
        for r in rows
    ]

    # Deduplicate drug ids
    unique = {}
    for d in drugs:
        unique[d['id']] = d.get('name')
    deduped = [{'id': k, 'name': v} for k, v in unique.items()]

    print(f"Updating {len(deduped)} drug nodes in Neo4j...")
    cypher_query = """
    UNWIND $records AS drug
    MATCH (d:Drug {concept_id: drug.id})
    SET d.name = drug.name
    """
    batch_size = 2000
    with neo4j_driver.session(database=database) as session:
        for i in range(0, len(deduped), batch_size):
            batch = deduped[i:i+batch_size]
            session.run(cypher_query, records=batch)
    print("✅ Drug names updated.")


def run_final_analysis(driver, database):
    """Runs the final analysis query and prints results to the terminal."""
    print("\n--- Running Final Analysis ---")

    # This is the final co-occurrence query for drug 1119119
    analysis_query = """
    // 1. Start with the target drug and find all its reports
    MATCH (d:Drug {concept_id: 1119119})<-[:MENTIONS_DRUG]-(report:Report)

    // 2. From those reports, find pairs of reactions
    MATCH (reaction1:Reaction)<-[:CONTAINS_REACTION]-(report)-[:CONTAINS_REACTION]->(reaction2:Reaction)

    // 3. Filter for valid pairs
    WHERE 
        elementId(reaction1) < elementId(reaction2) AND
        reaction1.name IS NOT NULL AND
        reaction2.name IS NOT NULL

    // 4. Count the co-occurrence pairs and return the most frequent
    RETURN
        reaction1.name AS reaction_1,
        reaction2.name AS reaction_2,
        count(*) AS co_occurrence_count
    ORDER BY
        co_occurrence_count DESC
    LIMIT 20;
    """
    try:
        with driver.session(database=database) as session:
            result = session.run(analysis_query)
            records = list(result)
            
            if not records:
                print("✅ Analysis ran, but no co-occurrence pairs were found for drug 1119119.")
                return

            # Print a header for the results
            print("\n✅ Top 20 Adverse Event Syndromes (for Drug 1119119):")
            print(f"{'Reaction 1':<30} | {'Reaction 2':<30} | {'Count':<10}")
            print("-" * 74)

            # Print each row of the results
            for record in records:
                print(f"{record['reaction_1']:<30} | {record['reaction_2']:<30} | {record['co_occurrence_count']:<10}")

    except Exception as e:
        print(f"❌ FAILED TO RUN ANALYSIS: {e}")


def main():
    sf_conn = None
    neo4j_driver = None
    try:
        sf_conn = get_snowflake_connection()
        neo4j_driver, neo4j_db = get_neo4j_driver()

        # 1. Set up Neo4j constraints
        setup_neo4j_schema(neo4j_driver, neo4j_db)

        # 2. Extract and load report relationships (batched)
        records = fetch_data_from_snowflake(sf_conn)
        if records:
            load_data_to_neo4j(neo4j_driver, neo4j_db, records)
        else:
            print("No report data was found in Snowflake to load.")

        # 3. Load the dictionary names
        load_reaction_names(sf_conn, neo4j_driver, neo4j_db)
        load_drug_names(sf_conn, neo4j_driver, neo4j_db)

        # 4. Run the final analysis and print results
        run_final_analysis(neo4j_driver, neo4j_db)

        print("--- Neo4j Load Finished ---")

    except Exception as exc:  # pylint: disable=broad-except
        print(f"An error occurred: {exc}")
        sys.exit(1)
    finally:
        if sf_conn:
            sf_conn.close()
            print("Snowflake connection closed.")
        if neo4j_driver:
            neo4j_driver.close()
            print("Neo4j connection closed.")


if __name__ == "__main__":
    main()
