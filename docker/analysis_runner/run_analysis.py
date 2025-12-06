import os
import sys

import duckdb
import networkx as nx
import numpy as np
import pandas as pd
import snowflake.connector
from networkx.algorithms import community as nx_comm
from scipy.stats import fisher_exact
from statsmodels.stats.multitest import multipletests

OUTPUT_DIR = "/app/output"
TOP_DRUG_LIMIT = 5
TOP_PER_DRUG_PAIR_LIMIT = 10000
TOP_N_RESULTS_TO_SAVE = 10000


def get_db_connection():
    try:
        return snowflake.connector.connect(
            user=os.environ['SNOWFLAKE_USER'],
            password=os.environ['SNOWFLAKE_PASSWORD'],
            account=os.environ['SNOWFLAKE_ACCOUNT'],
            warehouse=os.environ.get('SNOWFLAKE_WAREHOUSE', 'ETL_WH'),
            database=os.environ.get('SNOWFLAKE_DATABASE', 'PHARMACOVIGILANCE'),
            schema=os.environ.get('SNOWFLAKE_SCHEMA', 'PUBLIC'),
        )
    except Exception as exc:  # pylint: disable=broad-except
        print(f"FATAL: Failed to connect to Snowflake: {exc}", file=sys.stderr)
        sys.exit(1)


def get_top_drugs(conn, limit=TOP_DRUG_LIMIT):
    print(f"Querying for top {limit} drugs by report count...")
    query = f"""
        SELECT standard_concept_id
        FROM BRONZE_DRUG
        GROUP BY 1
        ORDER BY COUNT(DISTINCT primaryid) DESC
        LIMIT {limit}
    """
    df = pd.read_sql(query, conn)
    return df['STANDARD_CONCEPT_ID'].tolist()


def run_analysis():
    conn = get_db_connection()

    print(f"Preparing contingency data for analysis...")

    # Inspect table columns to decide which query pattern to use (per-drug or global)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE table_name = 'GOLD_CONTINGENCY_TABLE' "
            "AND table_schema = 'PUBLIC' AND table_catalog = current_database();"
        )
        cols_info = [r[0] for r in cur.fetchall()]
        print("Detected GOLD_CONTINGENCY_TABLE columns:", cols_info)
    except Exception as exc:
        print("Failed to query INFORMATION_SCHEMA for GOLD_CONTINGENCY_TABLE:", exc)
        cur.close()
        conn.close()
        return

    has_drug_id_column = 'DRUG_ID' in cols_info

    if has_drug_id_column:
        top_drug_ids = get_top_drugs(conn)
        if not top_drug_ids:
            print("ERROR: No drugs returned for analysis.", file=sys.stderr)
            conn.close()
            return
        placeholders = ', '.join(str(d) for d in top_drug_ids)
        max_rows = TOP_PER_DRUG_PAIR_LIMIT * max(1, len(top_drug_ids))
        contingency_query = f"""
            SELECT *
            FROM PHARMACOVIGILANCE.PUBLIC.GOLD_CONTINGENCY_TABLE
            WHERE DRUG_ID IN ({placeholders})
            ORDER BY N11 DESC
            LIMIT {max_rows}
        """
    else:
        print("No DRUG_ID column found; running global top-N contingency query.")
        # Fetch more rows to ensure we have enough for 10k results after filtering
        fetch_limit = TOP_N_RESULTS_TO_SAVE * 2  # Fetch 2x to account for filtering
        contingency_query = f"""
            SELECT *
            FROM PHARMACOVIGILANCE.PUBLIC.GOLD_CONTINGENCY_TABLE
            ORDER BY N11 DESC
            LIMIT {fetch_limit}
        """

    # Use a DBAPI cursor to fetch rows and build a DataFrame to avoid pandas.read_sql DB-API edge cases
    try:
        cur.execute(contingency_query)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        # Normalize column names to upper-case to match downstream expectations
        df_contingency = pd.DataFrame(rows, columns=[c.upper() for c in cols])
    except Exception as exc:
        print(f"ERROR running contingency query: {exc}")
        try:
            cur.execute("SELECT * FROM PHARMACOVIGILANCE.PUBLIC.GOLD_CONTINGENCY_TABLE LIMIT 1")
            sample = cur.fetchall()
            cols = [d[0] for d in cur.description]
            print("Sample row columns:", cols)
            print("Sample row (first):", sample[0] if sample else None)
        except Exception as e2:
            print("Could not SELECT sample row:", e2)
        cur.close()
        conn.close()
        return

    if df_contingency.empty:
        print("ERROR: Filtered GOLD_CONTINGENCY_TABLE is empty. Skipping analysis.", file=sys.stderr)
        conn.close()
        return

    print(f"Processing {len(df_contingency)} reaction pairs...")
    p_values = []
    odds_ratios = []
    for _, row in df_contingency.iterrows():
        table = [[row['N11'], row['N10']], [row['N01'], row['N00']]]
        odds_ratio, p_value = fisher_exact(table, alternative='greater')
        p_values.append(p_value)
        odds_ratios.append(odds_ratio)

    df_contingency['odds_ratio'] = odds_ratios
    reject, pvals_corrected, _, _ = multipletests(p_values, alpha=0.05, method='fdr_bh')
    df_contingency['p_adj'] = pvals_corrected
    df_contingency['significant'] = reject

    df_significant = df_contingency[df_contingency['significant']].copy()
    if 'RN' in df_significant.columns:
        df_significant = df_significant.drop(columns=['RN'])

    df_significant['co_occurrence'] = df_significant['N11']
    df_significant['p_value'] = df_significant['p_adj']
    df_significant['hybrid_score'] = np.log1p(
        df_significant['odds_ratio'].replace(0, np.nan).fillna(0)
    ) * df_significant['N11']
    print(f"Found {len(df_significant)} statistically significant pairs.")

    print("Loading dictionaries for merging...")
    dict_query = "SELECT outcome_concept_id, reaction_name FROM GOLD_REACTION_DICTIONARY"
    df_dict = pd.read_sql(dict_query, conn)
    df_dict.columns = df_dict.columns.str.upper()

    # Load drug dictionary if DRUG_ID column exists
    df_drug = None
    if has_drug_id_column:
        print("Loading drug dictionary...")
        drug_dict_query = "SELECT drug_id, drug_name FROM GOLD_DRUG_DICTIONARY"
        df_drug = pd.read_sql(drug_dict_query, conn)
        df_drug.columns = df_drug.columns.str.lower()

    conn.close() # Connection closed after all queries are done

    # 🚀 NEW: Use DuckDB for Heavy Lifting (Memory-Efficient Joins & Sorting)
    print("🚀 Using DuckDB to optimize heavy data processing (joins and sorting)...")
    print("   This prevents Out-of-Memory crashes when processing large datasets.")
    
    # DuckDB can query Pandas DataFrames directly!
    # We use it here to perform the joins and sorting which are memory-intensive in Pandas
    
    # Create in-memory DuckDB connection
    con = duckdb.connect(database=':memory:')
    
    # Normalize column names in df_significant for consistent access
    if 'reaction_1' not in df_significant.columns:
        if 'REACTION_1' in df_significant.columns:
            df_significant['reaction_1'] = df_significant['REACTION_1']
            df_significant['reaction_2'] = df_significant['REACTION_2']
            if 'DRUG_ID' in df_significant.columns:
                df_significant['drug_id'] = df_significant['DRUG_ID']
    
    # Register dataframes as virtual tables in DuckDB
    con.register('significant_pairs', df_significant)
    con.register('reaction_dict', df_dict)
    
    # Build the SQL query for DuckDB
    if has_drug_id_column and df_drug is not None:
        con.register('drug_dict', df_drug)
        dashboard_query = f"""
        SELECT 
            CAST(s.drug_id AS VARCHAR) as drug_id,
            d_drug.drug_name as Drug_Name_Full,
            r1.REACTION_NAME as Reaction_1_Name,
            r2.REACTION_NAME as Reaction_2_Name,
            s.N11 as co_occurrence,
            s.odds_ratio,
            s.p_adj as p_value,
            CAST(s.reaction_1 AS BIGINT) as reaction_1,
            CAST(s.reaction_2 AS BIGINT) as reaction_2,
            (LN(s.odds_ratio + 1) * s.N11) as hybrid_score
        FROM significant_pairs s
        LEFT JOIN reaction_dict r1 ON s.reaction_1 = r1.OUTCOME_CONCEPT_ID
        LEFT JOIN reaction_dict r2 ON s.reaction_2 = r2.OUTCOME_CONCEPT_ID
        LEFT JOIN drug_dict d_drug ON CAST(s.drug_id AS VARCHAR) = CAST(d_drug.drug_id AS VARCHAR)
        ORDER BY hybrid_score DESC
        LIMIT {TOP_N_RESULTS_TO_SAVE}
        """
    else:
        # No drug dictionary - use placeholder
        dashboard_query = f"""
        SELECT 
            'N/A' as drug_id,
            'N/A (Global)' as Drug_Name_Full,
            r1.REACTION_NAME as Reaction_1_Name,
            r2.REACTION_NAME as Reaction_2_Name,
            s.N11 as co_occurrence,
            s.odds_ratio,
            s.p_adj as p_value,
            CAST(s.reaction_1 AS BIGINT) as reaction_1,
            CAST(s.reaction_2 AS BIGINT) as reaction_2,
            (LN(s.odds_ratio + 1) * s.N11) as hybrid_score
        FROM significant_pairs s
        LEFT JOIN reaction_dict r1 ON s.reaction_1 = r1.OUTCOME_CONCEPT_ID
        LEFT JOIN reaction_dict r2 ON s.reaction_2 = r2.OUTCOME_CONCEPT_ID
        ORDER BY hybrid_score DESC
        LIMIT {TOP_N_RESULTS_TO_SAVE}
        """
    
    # Execute DuckDB query and get result back to Pandas
    df_dashboard = con.execute(dashboard_query).df()
    
    # Close DuckDB connection
    con.close()
    
    # Ensure drug_id is string type
    if 'drug_id' in df_dashboard.columns:
        df_dashboard['drug_id'] = df_dashboard['drug_id'].astype(str)
    
    # Generate Chart Label
    df_dashboard['Chart_Label'] = df_dashboard['Reaction_1_Name'].fillna(
        df_dashboard['reaction_1'].astype(str)
    )
    
    print(f"✅ DuckDB processing complete. Prepared {len(df_dashboard)} rows for dashboard.")
    print(f"   Memory-efficient joins and sorting handled by DuckDB OLAP engine.")

    print("Running Louvain Community Detection...")

    # Column names should already be normalized from DuckDB section above
    # Verify we have reaction columns
    if 'reaction_1' not in df_significant.columns:
        print("No reaction columns found in contingency results; skipping community detection.")
        communities = []

    G = nx.Graph()
    for _, row in df_significant.iterrows():
        # ensure we have reaction ids
        if pd.isna(row.get('reaction_1')) or pd.isna(row.get('reaction_2')):
            continue
        G.add_edge(int(row['reaction_1']), int(row['reaction_2']), weight=row.get('odds_ratio', 1.0))

    communities = []
    if G.number_of_edges() > 0:
        communities = list(nx_comm.louvain_communities(G, weight='weight', seed=42))
    print(f"Found {len(communities)} syndrome clusters.")

    community_rows = []
    for idx, cluster in enumerate(communities, start=1):
        for reaction_id in cluster:
            community_rows.append(
                {
                    'reaction_id': int(reaction_id),
                    'cluster_id': idx,
                    'cluster_size': len(cluster),
                }
            )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_dashboard.to_csv(os.path.join(OUTPUT_DIR, 'dashboard_data.csv'), index=False)
    df_significant.to_csv(os.path.join(OUTPUT_DIR, 'statistical_analysis.csv'), index=False)
    pd.DataFrame(community_rows).to_csv(os.path.join(OUTPUT_DIR, 'reaction_communities.csv'), index=False)
    df_dict.to_csv(os.path.join(OUTPUT_DIR, 'gold_reaction_dictionary.csv'), index=False)
    if df_drug is not None:
        df_drug.to_csv(os.path.join(OUTPUT_DIR, 'gold_drug_dictionary.csv'), index=False)

    print("\n✅ Analysis pipeline complete.")


if __name__ == '__main__':
    run_analysis()
