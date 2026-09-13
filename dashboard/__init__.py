"""Judge-facing Streamlit dashboard over RunSense's typed tables.

Separate from the ``runsense`` package on purpose: it is an optional read-only
viewer (``pip install '.[dashboard]'``), and the API must never depend on it.
"""
