import os
import sys

import networkx as nx
import numpy as np
import pandas as pd
import snowflake.connector
from networkx.algorithms import community as nx_comm
from scipy.stats import fisher_exact
from statsmodels.stats.multitest import multipletests

OUTPUT_DIR = "/app/output"
TOP_DRUG_LIMIT = 5
TOP_PER_DRUG_PAIR_LIMIT = 1000
TOP_N_RESULTS_TO_SAVE = 1000


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
    top_drug_ids = get_top_drugs(conn)
    if not top_drug_ids:
        print("ERROR: No drugs returned for analysis.", file=sys.stderr)
        conn.close()
        return

    print(f"Loading Top {TOP_PER_DRUG_PAIR_LIMIT} pairs for {len(top_drug_ids)} drugs...")
    placeholders = ', '.join(str(d) for d in top_drug_ids)
    contingency_query = f"""
        SELECT *
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY DRUG_ID ORDER BY N11 DESC) AS rn
            FROM GOLD_CONTINGENCY_TABLE
            WHERE DRUG_ID IN ({placeholders})
        )
        WHERE rn <= {TOP_PER_DRUG_PAIR_LIMIT}
    """
    df_contingency = pd.read_sql(contingency_query, conn)

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

    drug_dict_query = "SELECT drug_id, drug_name FROM GOLD_DRUG_DICTIONARY"
    df_drug = pd.read_sql(drug_dict_query, conn)
    df_drug.columns = df_drug.columns.str.lower()
    conn.close()

    df_merged = df_significant.merge(
        df_dict[['OUTCOME_CONCEPT_ID', 'REACTION_NAME']],
        left_on='REACTION_1',
        right_on='OUTCOME_CONCEPT_ID',
        how='left',
    ).rename(columns={'REACTION_NAME': 'Reaction_1_Name'}).drop(columns=['OUTCOME_CONCEPT_ID'])

    df_merged = df_merged.merge(
        df_dict[['OUTCOME_CONCEPT_ID', 'REACTION_NAME']],
        left_on='REACTION_2',
        right_on='OUTCOME_CONCEPT_ID',
        how='left',
    ).rename(columns={'REACTION_NAME': 'Reaction_2_Name'}).drop(columns=['OUTCOME_CONCEPT_ID'])

    df_merged = df_merged.merge(
        df_drug[['drug_id', 'drug_name']],
        left_on='DRUG_ID',
        right_on='drug_id',
        how='left',
    ).rename(columns={'drug_name': 'Drug_Name_Full'})

    df_merged = df_merged.rename(
        columns={
            'DRUG_ID': 'drug_id',
            'REACTION_1': 'reaction_1',
            'REACTION_2': 'reaction_2',
        }
    )
    df_merged['drug_id'] = df_merged['drug_id'].astype(str)

    df_dashboard = (
        df_merged.sort_values('hybrid_score', ascending=False)
        .head(TOP_N_RESULTS_TO_SAVE)
        .copy()
    )
    df_dashboard['Chart_Label'] = df_dashboard['Reaction_1_Name'].fillna(
        df_dashboard['reaction_1'].astype(str)
    )
    print(f"Prepared lightweight dashboard dataset with {len(df_dashboard)} rows.")

    print("Running Louvain Community Detection...")
    G = nx.Graph()
    for _, row in df_significant.iterrows():
        G.add_edge(row['reaction_1'], row['reaction_2'], weight=row['odds_ratio'])

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
    df_drug.to_csv(os.path.join(OUTPUT_DIR, 'gold_drug_dictionary.csv'), index=False)

    print("\n✅ Analysis pipeline complete.")


if __name__ == '__main__':
    run_analysis()
