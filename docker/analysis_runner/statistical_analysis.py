import os
import snowflake.connector
import pandas as pd
from scipy.stats import chi2_contingency, fisher_exact

def load_config():
    """Loads credentials from environment variables."""
    config = {
        "sf_account": os.getenv("SNOWFLAKE_ACCOUNT"),
        "sf_user": os.getenv("SNOWFLAKE_USER"),
        "sf_password": os.getenv("SNOWFLAKE_PASSWORD"),
        "sf_role": os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        "sf_db": os.getenv("SNOWFLAKE_DATABASE", "PHARMACOVIGILANCE"),
        "sf_wh": os.getenv("SNOWFLAKE_WAREHOUSE", "ETL_WH"),
        "sf_schema": os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
    }
    print("Configuration loaded.")
    return config


def get_snowflake_connection(config):
    """Establishes connection to Snowflake."""
    try:
        conn = snowflake.connector.connect(
            user=config["sf_user"],
            password=config["sf_password"],
            account=config["sf_account"],
            warehouse=config["sf_wh"],
            database=config["sf_db"],
            schema=config["sf_schema"],
            role=config["sf_role"]
        )
        print("✅ Snowflake connection successful.")
        return conn
    except Exception as e:
        print(f"❌ Snowflake connection failed: {e}")
        return None


def fetch_contingency_data(conn):
    """Fetches the contingency table and reaction names."""
    print("Fetching GOLD tables from Snowflake...")
    
    # Query the main table
    query = "SELECT * FROM GOLD_CONTINGENCY_TABLE;"
    with conn.cursor() as cur:
        cur.execute(query)
        df = cur.fetch_pandas_all()
        
    # Query the dictionary to get names
    dict_query = "SELECT OUTCOME_CONCEPT_ID, REACTION_NAME FROM GOLD_REACTION_DICTIONARY;"
    with conn.cursor() as cur:
        cur.execute(dict_query)
        dict_df = cur.fetch_pandas_all()

    if df.empty:
        print("⚠️ GOLD_CONTINGENCY_TABLE is empty. Did dbt run?")
        return None

    # Merge names onto the table
    df = pd.merge(df, dict_df, left_on='REACTION_1', right_on='OUTCOME_CONCEPT_ID', how='left')
    df = pd.merge(df, dict_df, left_on='REACTION_2', right_on='OUTCOME_CONCEPT_ID', how='left', suffixes=('_1', '_2'))
    
    # Clean up columns
    df = df.rename(columns={'REACTION_NAME_1': 'name_1', 'REACTION_NAME_2': 'name_2'})
    df = df[['name_1', 'name_2', 'N11', 'N10', 'N01', 'N00']]
    
    print(f"Fetched {len(df)} reaction pairs for analysis.")
    return df


def calculate_statistics(row):
    """Calculates Odds Ratio, Chi2, and p-value for a 2x2 table."""
    # Build the 2x2 contingency table
    #      R2_Yes | R2_No
    # R1_Yes [N11,   N10]
    # R1_No  [N01,   N00]
    table = [
        [row['N11'], row['N10']],
        [row['N01'], row['N00']]
    ]
    
    try:
        # Fisher's Exact Test (good for small counts)
        odds_ratio, p_value_fisher = fisher_exact(table)
    except ValueError:
        odds_ratio, p_value_fisher = (None, None) # Happens if all counts are 0
        
    try:
        # Chi-squared Test
        chi2, p_value_chi2, _, _ = chi2_contingency(table, correction=True) # Yates' correction
    except ValueError:
        chi2, p_value_chi2 = (None, None)

    row['odds_ratio'] = odds_ratio
    row['p_value_fisher'] = p_value_fisher
    row['p_value_chi2'] = p_value_chi2
    row['chi2'] = chi2
    return row


def main():
    config = load_config()
    sf_conn = get_snowflake_connection(config)
    if not sf_conn:
        return

    try:
        print("\n--- Running Statistical Analysis ---")
        df = fetch_contingency_data(sf_conn)
        
        if df is None:
            print("Exiting.")
            return

        # Run calculations for every row
        analysis_results = df.apply(calculate_statistics, axis=1)
        
        # Sort by the most statistically significant
        analysis_results = analysis_results.sort_values(by='p_value_fisher', ascending=True)

        print("\n✅ Statistical Analysis Complete.")
        print("Top 10 Most Significant Syndromes (by Fisher's p-value):")
        
        # Print the results to the terminal
        print(analysis_results[['name_1', 'name_2', 'odds_ratio', 'p_value_fisher']].head(10).to_string())

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if sf_conn:
            sf_conn.close()
            print("Snowflake connection closed.")

if __name__ == "__main__":
    main()
