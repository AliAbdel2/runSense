"""Minimal judge-facing view over RunSense's typed tables.

Run it with ``streamlit run dashboard/app.py`` after ``pip install '.[dashboard]'``.

The bundled web dashboard at ``/`` already shows one run's plan, trace and the
evaluation report. This page exists for the question that one cannot answer:
what has happened *across* runs and sessions. It reads ``tool_traces`` and
``alerts`` directly from the SQLite file (``RUNSENSE_DB``) rather than through the
API, so it works against a database the server is not currently serving.

Deliberately plain: filters, two tables and a button. All of its queries live in
``dashboard/data.py`` and are unit tested there; nothing below is more than
layout.
"""

from __future__ import annotations

import streamlit as st

from dashboard import data

ANY = "(any)"


def _optional(choice: str) -> str | None:
    return None if choice == ANY else choice


def main() -> None:
    st.set_page_config(page_title="RunSense observability", layout="wide")
    st.title("RunSense observability")
    st.caption(f"Reading {data.database_path()} directly. Raw provider responses and GPS "
               "coordinates are never recorded here.")

    limit = st.sidebar.slider("Rows", min_value=10, max_value=1000, value=data.DEFAULT_LIMIT, step=10)

    st.header("Tool traces")
    run_choice = st.selectbox("Run", [ANY, *data.run_ids(limit)])
    traces = data.recent_traces(_optional(run_choice), limit)
    st.write(f"{len(traces)} step(s)")
    st.dataframe(traces)

    st.header("Perception alerts")
    session_id = st.text_input("Session id", value="").strip()
    tier_choice = st.selectbox("Tier", [ANY, *data.tiers(limit)])
    alerts = data.recent_alerts(session_id or None, _optional(tier_choice), limit)
    st.write(f"{len(alerts)} alert(s)")
    st.dataframe(alerts)
    st.caption("Triage output from the server-side pipeline. Real-world detection recall, zone "
               "accuracy and end-to-end latency remain unmeasured.")

    st.header("Evaluation")
    if st.button("Run evaluation now"):
        report = data.evaluation_report()
        st.metric("Agent scenarios passed", f"{report['passed']}/{report['total']}")
        st.dataframe(report["results"])
        st.caption(report["scope"])
        st.subheader("Perception")
        st.json(report["perception"])


if __name__ == "__main__":  # Streamlit runs this file as the main script
    main()
