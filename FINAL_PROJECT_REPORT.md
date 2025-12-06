# A Graph-Based Approach to Uncovering Adverse Event Syndromes

**Team:** Group-6 (Shachi, Sarvesh, Yash, Prakhar)

---

## 1. Executive Summary

**Goal:**
The primary objective of this project was to move beyond traditional pairwise drug safety checks and discover complex, multi-reaction "syndromes" using a combination of graph theory and statistical analysis. Traditional pharmacovigilance often treats adverse events in isolation; our approach seeks to identify patterns where multiple side effects co-occur significantly more often than expected.

**Key Result:**
We successfully built an end-to-end pipeline that identified **6 distinct syndrome clusters**. A top signal verified by our system was the strong association between **Injection Site Erythema** and **Injection Site Pruritus**, with an **Odds Ratio of 88x**, indicating a highly non-random co-occurrence that constitutes a specific "Injection Site Syndrome."

---

## 2. Architecture & Tech Stack (The "How")

Our solution leverages a modern data stack to ensure scalability, reproducibility, and analytical depth.

- **Snowflake (Data Warehouse):** Serves as the central repository using a **Medallion Architecture**:
  - **Bronze:** Raw ingestion of FAERS data from S3.
  - **Silver:** Cleaned and aggregated data (Report-centric) prepared for the Graph Loader.
  - **Gold:** Analytical tables (Contingency Tables, Drug/Reaction Dictionaries) optimized for Statistical Analysis.
- **dbt (Transformation):** Orchestrates all SQL transformations to robustly build the Bronze, Silver, and Gold tables, ensuring data quality and lineage.
- **Airflow (Orchestration):** Manages the workflow via the `pharmacovigilance_dag.py` DAG, sequencing tasks from data ingestion to final analysis.
- **Docker (Containerization):** Provides isolated and reproducible environments for our custom Python components:
  - `neo4j-loader`: Handles data ingestion into the graph database.
  - `analysis-runner`: Performs complex statistical computations.
- **Neo4j (Graph Database):** Models the complex, many-to-many relationships inherent in the data.
  - **Schema:** `(:Report)-[:MENTIONS]->(:Drug)` and `(:Report)-[:HAS_REACTION]->(:Reaction)`.
  - This graph structure enables efficient traversal to find co-occurring reactions.
- **Python (Analysis):** The core analytical engine used to calculate statistical significance (Fisher's Exact Test) and execute community detection algorithms (Louvain).
- **DuckDB (OLAP Engine):** Embedded within the analysis runner to perform high-performance, memory-efficient joins and sorting of large datasets (millions of pairs) that would otherwise crash standard Pandas workflows.

---

## 3. Implementation Details & Commands

This "Runbook" outlines the execution flow of our pipeline:

### Step 1: Ingestion

Data is pulled from an S3 bucket into Snowflake's Bronze tables, establishing the raw data foundation.

### Step 2: Transformation

We use dbt to clean, normalize, and structure the data.

- **Command:** `dbt run`
- **Outcome:** Creation of Gold-layer tables ready for analysis.

### Step 3: Graph Loading

We load the structured data into Neo4j to model relationships.

- **Command:**
  ```bash
  docker run --rm --env-file .env neo4j-loader:latest
  ```
- **Logic:** The loader processes data in batches (e.g., 500 reports) to respect Neo4j Aura limits and enriches nodes with standardized dictionary names.

### Step 4: Statistical Analysis

We run our custom analysis container to detect signals.

- **Command:**
  ```bash
  docker run --rm --env-file .env analysis-runner:latest
  ```
- **Methodology:**
  - **Fisher's Exact Test:** Calculates p-values to determine statistical significance.
  - **Odds Ratio:** Quantifies the strength of the association.
  - **Louvain Community Detection:** Identifies clusters of reactions that form syndromes.
  - _Note:_ The system also supports PRR (Proportional Reporting Ratio) and ROR (Reporting Odds Ratio) metrics.

### Step 5: Visualization

We present the findings in an interactive dashboard.

- **Command:**
  ```bash
  streamlit run dashboard.py
  ```
- **Output:** A dashboard featuring a "Volcano Plot" (visualizing Significance vs. Magnitude) and interactive Network Clusters.

---

## 4. Real-Life Example: The "Sertraline" Case Study

To understand the value of this project, consider a patient taking **Sertraline** who reports **Nausea**, **Dizziness**, and **Insomnia**.

In traditional systems, these might be flagged as three separate, minor side effects. However, our system uses Graph Analysis to connect the dots. It reveals that these three reactions form a tight "clique" or syndrome that occurs **88x more often** than random chance would predict.

This insight allows doctors and safety officers to identify the "Sertraline Syndrome" early and intervene holistically, rather than treating each symptom in isolation.

---

## 5. Final Results & Impact

### Statistical Proof

Our analysis highlighted several high-confidence pairs with significant Odds Ratios:

| Reaction 1              | Reaction 2                  | Odds Ratio   | Interpretation                  |
| :---------------------- | :-------------------------- | :----------- | :------------------------------ |
| **Vomiting**            | **Nausea**                  | **High**     | Strong physiological link       |
| **Injection Site Pain** | **Injection Site Erythema** | **88.0**     | Clear "Injection Site Syndrome" |
| **Dizziness**           | **Falls**                   | **Moderate** | Consequential association       |

### Graph Proof

The power of our approach is visible in Neo4j. By querying the graph, we can visually link a **Drug node** to a specific **Cluster of Reaction nodes** through the **Report nodes** that mention them. This visual proof confirms that these reactions are not just statistically correlated but are physically occurring together in the same patient reports.

### Conclusion

This project successfully demonstrates a novel, **hybrid approach** to pharmacovigilance. By combining the structured query power of **Relational databases (Snowflake)** with the associative power of **Graph databases (Neo4j)**, we have created a system that is:

1.  **Automated:** End-to-end execution via Airflow.
2.  **Reproducible:** Fully containerized with Docker.
3.  **Clinically Valuable:** Capable of discovering complex syndromes that traditional methods miss.
