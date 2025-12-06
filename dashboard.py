import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx
from pathlib import Path

# --- Constants ---
STATS_FILE = 'output/statistical_analysis.csv'
DRUG_DICTIONARY_FILE = 'output/gold_drug_dictionary.csv'
COMMUNITIES_FILE = 'output/reaction_communities.csv'
BASE_DIR = Path(__file__).resolve().parent

# --- Page Config ---
st.set_page_config(layout='wide', page_title='Adverse Event Dashboard')

# --- Helper Functions ---
@st.cache_data
def load_data():
    try:
        # 1. Load Stats
        df_stats = pd.read_csv(BASE_DIR / STATS_FILE)
        df_stats.columns = df_stats.columns.str.upper()

        # 2. Load Drug Dictionary
        df_drug_dict = pd.read_csv(BASE_DIR / DRUG_DICTIONARY_FILE)
        df_drug_dict.columns = df_drug_dict.columns.str.lower()
        df_drug_dict['drug_id'] = df_drug_dict['drug_id'].astype(str)

        # 2b. Load Reaction Dictionary
        REACTION_DICT_FILE = 'output/gold_reaction_dictionary.csv'
        if (BASE_DIR / REACTION_DICT_FILE).exists():
            df_reaction_dict = pd.read_csv(BASE_DIR / REACTION_DICT_FILE)
            df_reaction_dict.columns = df_reaction_dict.columns.str.upper()
            # Ensure ID is string/int consistent
            # statistical_analysis.csv has IDs as int or string? Let's assume int for merge or convert both
        else:
            df_reaction_dict = pd.DataFrame()

        # 3. Normalize DRUG_ID
        if 'DRUG_ID' not in df_stats.columns:
            if 'drug_id' in df_stats.columns:
                df_stats['DRUG_ID'] = df_stats['drug_id']
            else:
                df_stats['DRUG_ID'] = 'N/A'
        
        df_stats['DRUG_ID'] = df_stats['DRUG_ID'].fillna('N/A').astype(str)

        # 4. Handle Drug Names
        # Logic: If DRUG_ID is 'N/A', it's the Global Dataset. Otherwise, merge.
        
        # Create a temp column for merging
        df_stats['drug_id_merge'] = df_stats['DRUG_ID'].str.lower()
        
        # Merge only for non-N/A rows (conceptually) - actually merge all left, then fix N/A
        df_stats = df_stats.merge(
            df_drug_dict[['drug_id', 'drug_name']],
            left_on='drug_id_merge', right_on='drug_id',
            how='left'
        ).rename(columns={'drug_name': 'Drug_Name_Full'})
        
        # Explicitly fix the "Global Dataset" label
        df_stats.loc[df_stats['DRUG_ID'] == 'N/A', 'Drug_Name_Full'] = 'Global Dataset (All Drugs)'
        
        # Fill remaining unknowns
        df_stats['Drug_Name_Full'] = df_stats['Drug_Name_Full'].fillna('Unknown Drug')
        
        # Cleanup merge columns
        df_stats = df_stats.drop(columns=['drug_id_merge', 'drug_id'], errors='ignore')

        # 4b. Handle Reaction Names (Map IDs to Names)
        if not df_reaction_dict.empty and 'OUTCOME_CONCEPT_ID' in df_reaction_dict.columns:
             # Prepare dict for faster mapping
             reaction_map = dict(zip(df_reaction_dict['OUTCOME_CONCEPT_ID'], df_reaction_dict['REACTION_NAME']))
             
             # Map Reaction 1
             if 'REACTION_1' in df_stats.columns:
                 df_stats['REACTION_1_NAME'] = df_stats['REACTION_1'].map(reaction_map).fillna(df_stats['REACTION_1'].astype(str))
             
             # Map Reaction 2
             if 'REACTION_2' in df_stats.columns:
                 df_stats['REACTION_2_NAME'] = df_stats['REACTION_2'].map(reaction_map).fillna(df_stats['REACTION_2'].astype(str))
        else:
             # Fallback if dict missing
             if 'REACTION_1' in df_stats.columns: df_stats['REACTION_1_NAME'] = df_stats['REACTION_1'].astype(str)
             if 'REACTION_2' in df_stats.columns: df_stats['REACTION_2_NAME'] = df_stats['REACTION_2'].astype(str)

        # 5. Calculate Metrics for Plots
        # Ensure numeric types
        cols_to_numeric = ['ODDS_RATIO', 'P_ADJ', 'N11']
        for col in cols_to_numeric:
            if col in df_stats.columns:
                df_stats[col] = pd.to_numeric(df_stats[col], errors='coerce').fillna(0)

        # Log Odds Ratio (for Volcano X-axis)
        # Avoid log(0) by adding small epsilon if needed, or just handle infs
        df_stats['log_odds_ratio'] = np.log2(df_stats['ODDS_RATIO'].replace(0, np.nan)).fillna(0)
        
        # -Log10 P-value (for Volcano Y-axis)
        # Avoid log(0)
        df_stats['neg_log10_p_val'] = -np.log10(df_stats['P_ADJ'].replace(0, 1e-300))

        # Hybrid Score for sorting
        if 'HYBRID_SCORE' not in df_stats.columns:
             df_stats['HYBRID_SCORE'] = np.log1p(df_stats['ODDS_RATIO']) * df_stats['N11']

        # Chart Label
        if 'CHART_LABEL' not in df_stats.columns:
             df_stats['CHART_LABEL'] = df_stats['REACTION_1_NAME'].fillna('Unknown')

        return df_stats

    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()

@st.cache_data
def load_communities():
    try:
        if (BASE_DIR / COMMUNITIES_FILE).exists():
            df = pd.read_csv(BASE_DIR / COMMUNITIES_FILE)
            df.columns = df.columns.str.lower()
            return df
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# --- Plotting Functions ---

def plot_volcano(df):
    """Creates a Volcano Plot using Plotly."""
    # Filter for reasonable display (remove extreme outliers if needed, but keeping all for now)
    
    # Color logic: Significant if p_adj < 0.05 AND Odds Ratio > 1 (Log2 > 0)
    df['Significance'] = 'Not Significant'
    df.loc[(df['P_ADJ'] < 0.05) & (df['log_odds_ratio'] > 0), 'Significance'] = 'Significant (Positive)'
    df.loc[(df['P_ADJ'] < 0.05) & (df['log_odds_ratio'] < 0), 'Significance'] = 'Significant (Negative)'

    fig = px.scatter(
        df,
        x="log_odds_ratio",
        y="neg_log10_p_val",
        color="Significance",
        hover_data=['REACTION_1_NAME', 'REACTION_2_NAME', 'ODDS_RATIO', 'P_ADJ'],
        color_discrete_map={
            'Significant (Positive)': '#FF4B4B',  # Streamlit Red
            'Significant (Negative)': '#0068C9',  # Streamlit Blue
            'Not Significant': 'grey'
        },
        title="Volcano Plot: Statistical Significance vs. Association Strength",
        labels={
            "log_odds_ratio": "Log2(Odds Ratio) [Strength]",
            "neg_log10_p_val": "-Log10(P-Value) [Significance]"
        }
    )
    
    # Add threshold lines
    fig.add_hline(y=-np.log10(0.05), line_dash="dash", line_color="gray", annotation_text="p=0.05")
    fig.add_vline(x=0, line_dash="dash", line_color="gray", annotation_text="OR=1")
    
    fig.update_layout(height=600)
    return fig

def plot_network_graph(df_top_pairs, df_communities):
    """Creates a Network Graph of top co-occurring reactions."""
    G = nx.Graph()
    
    # 1. Add Edges from Top Pairs
    # We use the top N pairs to define the edges
    for _, row in df_top_pairs.iterrows():
        r1 = row['REACTION_1_NAME']
        r2 = row['REACTION_2_NAME']
        weight = row['N11']
        # Add edge
        G.add_edge(r1, r2, weight=weight)

    # 2. Add Node Attributes (Community)
    # Create a mapping from reaction name to cluster_id
    # Note: communities file has reaction_id, we might need to map names if available
    # For this demo, we'll try to map if possible, or just use connected components if file missing
    
    node_colors = []
    node_text = []
    
    # Position nodes using spring layout
    pos = nx.spring_layout(G, seed=42)
    
    # Create Plotly Traces
    edge_x = []
    edge_y = []
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=0.5, color='#888'),
        hoverinfo='none',
        mode='lines')

    node_x = []
    node_y = []
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node)

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode='markers',
        hoverinfo='text',
        marker=dict(
            showscale=True,
            colorscale='YlGnBu',
            reversescale=True,
            color=[],
            size=10,
            colorbar=dict(
                thickness=15,
                title='Node Connections',
                xanchor='left'
            ),
            line_width=2))

    # Color nodes by degree (number of connections)
    node_adjacencies = []
    for node, adjacencies in enumerate(G.adjacency()):
        node_adjacencies.append(len(adjacencies[1]))
    
    node_trace.marker.color = node_adjacencies
    node_trace.text = node_text

    fig = go.Figure(data=[edge_trace, node_trace],
                layout=go.Layout(
                    title=dict(
                        text='Network Graph of Top Co-occurring Reactions',
                        font=dict(size=16)
                    ),
                    showlegend=False,
                    hovermode='closest',
                    margin=dict(b=20,l=5,r=5,t=40),
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False))
                )
    return fig

# --- Main App ---

def main():
    # --- Header ---
    st.title('🩺 Pharmacovigilance Adverse Event Detection Pipeline')
    st.markdown("""
    ### 🎯 Project Goal
    Identify **statistically significant associations** between drugs and adverse reactions using a modern data stack (Snowflake, dbt, Neo4j).
    """)
    st.markdown('---')

    # --- Sidebar ---
    with st.sidebar:
        st.header("ℹ️ About This Project")
        st.info("""
        **Pipeline Flow:**
        1. **Ingestion**: S3 -> Snowflake (Bronze)
        2. **Transformation**: dbt (Silver -> Gold)
        3. **Graph**: Neo4j (Louvain Communities)
        4. **Stats**: Fisher's Exact Test
        """)
        
        st.markdown("---")
        st.header("📚 Algorithms Explained")
        
        with st.expander("Fisher's Exact Test (Odds Ratio)"):
            st.write("""
            Measures the **strength of association** between a drug and a reaction.
            - **Odds Ratio > 1**: Positive association (Risk).
            - **P-Value < 0.05**: Statistically significant.
            """)
            
        with st.expander("Louvain Community Detection"):
            st.write("""
            A graph algorithm that finds **clusters** of reactions that frequently appear together.
            - These clusters represent potential **syndromes**.
            """)

    # --- Load Data ---
    df_all = load_data()
    df_communities = load_communities()

    if df_all.empty:
        st.error("No data found. Please run the pipeline first.")
        return

    # --- Top Metrics ---
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Significant Pairs", f"{len(df_all):,}", help="p-adj < 0.05")
    with c2:
        unique_drugs = df_all['DRUG_ID'].nunique()
        st.metric("Unique Drugs", f"{unique_drugs:,}")
    with c3:
        unique_reactions = df_all['REACTION_1_NAME'].nunique()
        st.metric("Unique Reactions", f"{unique_reactions:,}")

    st.markdown('---')

    # --- Filter Section ---
    if 'DRUG_ID' in df_all.columns:
        # Get list of drugs, ensure Global is first
        drugs = sorted([d for d in df_all['DRUG_ID'].unique() if d != 'N/A'])
        
        # Create labels
        drug_labels = {}
        for d in drugs:
            name = df_all[df_all['DRUG_ID'] == d]['Drug_Name_Full'].iloc[0]
            drug_labels[d] = f"{d} ({name})"
            
        options = ['Global Dataset (All Drugs)'] + [drug_labels[d] for d in drugs]
        
        st.sidebar.header("🔍 Analysis Scope")
        selected_label = st.sidebar.selectbox("Select Drug:", options)
        
        if selected_label == 'Global Dataset (All Drugs)':
            df_filtered = df_all[df_all['DRUG_ID'] == 'N/A'].copy()
            # Fallback: if N/A rows don't exist (e.g. running on single drug data), show all
            if df_filtered.empty:
                df_filtered = df_all.copy()
            st.subheader("🌍 Global Analysis Results")
        else:
            selected_id = selected_label.split(' ')[0]
            df_filtered = df_all[df_all['DRUG_ID'] == selected_id].copy()
            st.subheader(f"💊 Analysis for: {selected_label}")
    else:
        df_filtered = df_all.copy()

    # --- Tabbed View for Visualizations ---
    tab1, tab2, tab3 = st.tabs(["📊 Statistical Significance", "🕸️ Network Graph", "📋 Data Table"])

    with tab1:
        st.subheader("Volcano Plot: Identifying Signals from Noise")
        st.caption("Points in the top-right (Red) are highly significant AND strongly associated.")
        
        if not df_filtered.empty:
            fig_volcano = plot_volcano(df_filtered)
            st.plotly_chart(fig_volcano, use_container_width=True)
        else:
            st.info("No data available for this selection.")

    with tab2:
        st.subheader("Syndrome Network Graph")
        st.caption("Visualizing how adverse reactions co-occur. Nodes are reactions, edges are co-occurrences.")
        
        # Filter for top N pairs to avoid hairball
        top_n_network = 50
        df_network = df_filtered.sort_values('N11', ascending=False).head(top_n_network)
        
        if not df_network.empty:
            fig_network = plot_network_graph(df_network, df_communities)
            st.plotly_chart(fig_network, use_container_width=True)
        else:
            st.info("Not enough data to generate network graph.")

    with tab3:
        st.subheader("Top Significant Associations")
        
        # Prepare table
        df_table = df_filtered.sort_values('HYBRID_SCORE', ascending=False).head(15).copy()
        
        # Select and Rename Columns
        cols_map = {
            'Drug_Name_Full': 'Drug',
            'REACTION_1_NAME': 'Reaction 1',
            'REACTION_2_NAME': 'Reaction 2',
            'ODDS_RATIO': 'Odds Ratio',
            'P_ADJ': 'P-Value (Adj)',
            'N11': 'Co-occurrence'
        }
        
        # Filter columns that exist
        cols_to_show = [c for c in cols_map.keys() if c in df_table.columns]
        df_display = df_table[cols_to_show].rename(columns=cols_map)
        
        # Format Floats
        st.dataframe(
            df_display.style.format({
                'Odds Ratio': '{:.2f}',
                'P-Value (Adj)': '{:.2e}',
                'Co-occurrence': '{:.0f}'
            }),
            use_container_width=True
        )

if __name__ == '__main__':
    main()
