import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = Path(__file__).parent / "github_pipeline.db"

st.set_page_config(
    page_title="GitHub Repository Explorer",
    page_icon="📊",
    layout="wide",
)

st.title("GitHub Repository Explorer")
st.caption(
    "A snapshot of public GitHub repositories matching "
    "the data-engineering search query."
)

if not DB_PATH.exists():
    st.error("Database not found. Run the ingestion pipeline first.")
    st.stop()

with sqlite3.connect(DB_PATH) as conn:
    language_df = pd.read_sql_query("""
        SELECT language, repository_count, average_stars, total_stars
        FROM report_language_summary
        ORDER BY repository_count DESC
    """, conn)

    top_df = pd.read_sql_query("""
        SELECT full_name, language, stars, forks, html_url
        FROM report_top_repositories
        ORDER BY stars DESC
    """, conn)

    refresh_df = pd.read_sql_query("""
        SELECT MAX(fetched_at) AS last_fetched
        FROM raw_api_responses
    """, conn)

if language_df.empty or top_df.empty:
    st.warning("No reporting data found. Run the pipeline first.")
    st.stop()

total_repos = int(language_df["repository_count"].sum())
total_stars = int(language_df["total_stars"].sum())
last_fetched = refresh_df.loc[0, "last_fetched"]

c1, c2, c3 = st.columns(3)
c1.metric("Unique repositories", f"{total_repos:,}")
c2.metric("Total stars in sample", f"{total_stars:,}")
c3.metric("Last fetched (UTC)", str(last_fetched or "Unknown"))

st.subheader("Programming language breakdown")

language_chart = px.bar(
    language_df.head(10),
    x="language",
    y="repository_count",
    labels={
        "language": "Programming language",
        "repository_count": "Number of repositories",
    },
    hover_data=["average_stars", "total_stars"],
)
st.plotly_chart(language_chart, use_container_width=True)

st.subheader("Top repositories by stars")

top_chart = px.bar(
    top_df.head(10).sort_values("stars"),
    x="stars",
    y="full_name",
    orientation="h",
    labels={"stars": "GitHub stars", "full_name": "Repository"},
    hover_data=["language", "forks"],
)
st.plotly_chart(top_chart, use_container_width=True)

st.subheader("Repository details")
st.dataframe(
    top_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "html_url": st.column_config.LinkColumn("Repository URL")
    },
)

st.caption(
    "Interpretation: these results represent the repositories returned "
    "by our configured GitHub search, not all GitHub repositories. "
    "Stars are cumulative and do not measure current activity or quality."
)
