# GitHub Repository Explorer

A small end-to-end data engineering project that collects public
GitHub repository data, stores raw API responses in SQLite, transforms
them into structured tables, and presents summary metrics in Streamlit.

## Architecture

GitHub REST API -> Python ingestion -> SQLite raw layer
-> clean repository table -> reporting tables -> Streamlit dashboard

## API choice

This project uses GitHub's public repository search API with the query
`data-engineering`.

Basic unauthenticated access does not require an API key, but has
stricter rate limits. The pipeline fetches up to three pages of 100
repositories each.

The results are a sample of repositories returned by this query, not
a complete catalogue of GitHub repositories.

## Data model

- `raw_api_responses`: original JSON response for each successful page,
  including the query, page, fetch timestamp, and HTTP status.
- `clean_repositories`: one current record per repository, keyed by
  GitHub repository ID.
- `report_language_summary`: repository counts and star aggregates
  grouped by language.
- `report_top_repositories`: the ten repositories with the most stars
  in the collected data.

Missing languages are reported as `Unknown`. Records without a
repository ID or name are skipped.

## Metrics

1. Repository count by primary programming language.
2. Top ten repositories by accumulated stars.

Stars are a measure of accumulated interest, not current activity,
project quality, or proof of adoption.

## Requirements

Python 3.10 or newer is recommended.

Install dependencies:

    pip install -r requirements.txt

## Run the pipeline

    python pipeline.py

This fetches data, stores raw responses, refreshes the clean table,
and rebuilds reporting tables in `github_pipeline.db`.

The pipeline runs on demand; no scheduler or cloud infrastructure
is required.

## Run the dashboard

After running the pipeline:

    streamlit run app.py

Open the local URL printed by Streamlit in your browser.

## Reliability and tradeoffs

- Requests have timeouts.
- Temporary server errors and rate-limit responses are retried.
- Pagination is bounded to three pages to keep the exercise small.
- Raw responses are retained for reprocessing.
- The clean table uses the repository ID as its primary key and
  updates existing records on reruns.
- SQLite keeps setup simple and avoids external infrastructure.
- The project does not implement continuous scheduling or a
  production-grade incremental ingestion framework.

## AI-use disclosure

AI tools helped with implementation planning, code drafting, and
reviewing potential edge cases. I ran the pipeline and inspected its
outputs in Google Colab. I reviewed the data model, retry behavior,
rerun handling, and metric definitions. The final implementation and
its limitations are documented here.

Before submission, update this section to accurately describe the AI
assistance you used and the checks you personally completed.
