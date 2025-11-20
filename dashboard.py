# dashboard.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np  # kept to preserve original imports (even if unused)
import pandas as pd
import streamlit as st


# ╭──────────────────────────────────────────────────────────────────────────────╮
# │ Configuration & Constants                                                    │
# ╰──────────────────────────────────────────────────────────────────────────────╯
@dataclass(frozen=True)
class UiConfig:
    page_title: str = "Adverse Event Syndrome Pipeline"
    app_heading: str = "🩺 Adverse Event Syndrome Discovery Dashboard"
    header_sep: str = "---"
    top_n_default: int = 10
    chart_height: int = 400


@dataclass(frozen=True)
class ColumnConfig:
    table_columns: List[str] = (
        "Reaction_1_Name",
        "Reaction_2_Name",
        "co_occurrence",
        "odds_ratio",
        "p_value",
    )
    rename_map: Dict[str, str] = None
    chart_label_col: str = "Chart_Label"

    def __post_init__(self):
        # Workaround for dataclass default mutables
        if self.rename_map is None:
            object.__setattr__(
                self,
                "rename_map",
                {
                    "co_occurrence": "Co-occurrence Count",
                    "odds_ratio": "Odds Ratio (Strength)",
                    "p_value": "P-Value (Adjusted)",
                },
            )


UI = UiConfig()
COLS = ColumnConfig()


# ╭──────────────────────────────────────────────────────────────────────────────╮
# │ Data Loading                                                                 │
# ╰──────────────────────────────────────────────────────────────────────────────╯
@st.cache_data
def load_data() -> pd.DataFrame:
    """
    Loads **hardcoded** deterministic data used for the demo UI.
    Keeping parity with original content and schema.

    Returns:
        A DataFrame including a precomputed column used for chart labels.
    """
    try:
        data = {
            "drug_id": [
                "1501700", "1501700",
                "1119119", "1119119", "1119119", "1119119", "1119119", "1119119",
                "1151789", "1151789",
            ],
            "Drug_Name_Full": [
                "Drug 1501700", "Drug 1501700",
                "SERT...", "SERT...", "SERT...", "SERT...", "SERT...", "SERT...",
                "Drug 1151789", "Drug 1151789",
            ],
            "Reaction_1_Name": [
                "Nausea", "Vomiting",
                "Injection site pain", "Pain in extremity", "Injection site papule",
                "Injection site erythema", "Nasopharyngitis", "Vomiting",
                "Headache", "Dizziness",
            ],
            "Reaction_2_Name": [
                "Vomiting", "Headache",
                "DEVICE MALFUNCTION", "Arthralgia", "Injection site pruritus",
                "Injection site pruritus", "Cough", "Nausea",
                "Dizziness", "Nausea",
            ],
            "co_occurrence": [191, 150, 5, 5, 4, 4, 4, 3, 1116, 1000],
            "odds_ratio": [350.8, 200.1, 88.5, 75.2, 70.1, 68.0, 65.3, 50.1, 13.6, 12.1],
            "p_value": [0.0] * 10,
            # Placeholder IDs (kept, do not affect UI)
            "reaction_1": [35808976, 35809011, 123, 456, 789, 101, 102, 103, 104, 105],
            "reaction_2": [35809011, 35808976, 456, 789, 101, 102, 103, 104, 105, 106],
        }
        df = pd.DataFrame(data)
        df[COLS.chart_label_col] = df["Reaction_1_Name"] + " + " + df["Reaction_2_Name"]
        return df
    except Exception as exc:  # pragma: no cover (Streamlit path)
        st.error(f"Error loading hardcoded data: {exc}")
        return pd.DataFrame()


# ╭──────────────────────────────────────────────────────────────────────────────╮
# │ UI Helpers                                                                   │
# ╰──────────────────────────────────────────────────────────────────────────────╯
def build_drug_name_map(df: pd.DataFrame) -> Dict[str, str]:
    """drug_id → Drug_Name_Full mapping."""
    return dict(zip(df["drug_id"], df["Drug_Name_Full"]))


def format_options(drug_ids: List[str], names: Dict[str, str]) -> List[str]:
    """
    Format options like "1119119 (SERT...)" while preserving original UX.
    """
    return [f"{did} ({names.get(did, 'Unknown')})" for did in drug_ids]


def parse_selected_id(display_value: str) -> str:
    """
    Extract drug_id from "1119119 (SERT...)". Matches original `split(" ")[0]`.
    """
    return display_value.split(" ", 1)[0]


def filter_top_pairs(df: pd.DataFrame, drug_id: str, top_n: int) -> pd.DataFrame:
    """
    Filter by drug_id and truncate to top N, preserving original ordering.
    """
    return df[df["drug_id"] == drug_id].head(top_n).copy()


def render_table(df: pd.DataFrame) -> None:
    st.dataframe(
        df[list(COLS.table_columns)].rename(columns=COLS.rename_map),
        use_container_width=True,
    )


def render_chart(df: pd.DataFrame) -> None:
    st.subheader("Odds Ratio Strength")
    chart_data = df.set_index(COLS.chart_label_col)["odds_ratio"]
    st.bar_chart(chart_data, height=UI.chart_height)


# ╭──────────────────────────────────────────────────────────────────────────────╮
# │ App                                                                          │
# ╰──────────────────────────────────────────────────────────────────────────────╯
def main() -> None:
    st.set_page_config(layout="wide", page_title=UI.page_title)
    st.title(UI.app_heading)
    st.markdown(UI.header_sep)

    df_all = load_data()
    if df_all.empty:
        st.error("FATAL ERROR: No data could be loaded.")
        return

    available_drugs = sorted(df_all["drug_id"].unique().tolist())
    name_map = build_drug_name_map(df_all)
    options = format_options(available_drugs, name_map)

    st.info(f"Displaying Top Results for {len(available_drugs)} High-Signal Drugs")

    selected_display = st.selectbox("Select Drug to Analyze:", options=options)
    selected_id = parse_selected_id(selected_display)

    top_n = UI.top_n_default
    df_filtered = filter_top_pairs(df_all, selected_id, top_n)

    st.header(f"Top {top_n} Significant Syndrome Pairs for {selected_display}")

    if df_filtered.empty:
        st.warning("No significant pairs available for this selection.")
        return

    render_table(df_filtered)
    render_chart(df_filtered)


if __name__ == "__main__":
    main()
