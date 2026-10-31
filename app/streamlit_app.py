"""Streamlit front end. Run the API first, then: uv run streamlit run app/streamlit_app.py"""
import pandas as pd
import streamlit as st

import client

EXAMPLES = [
    "What is the total revenue?",
    "What are the top 5 countries by revenue?",
    "Plot monthly revenue for 2011.",
    "Segment customers with RFM.",
]
MAX_HISTORY = 10

st.set_page_config(page_title="AI Analyst Agent", page_icon="📊")
st.session_state.setdefault("question", "")
st.session_state.setdefault("history", [])
st.session_state.setdefault("run", False)


def _use_example(q: str) -> None:
    st.session_state.question = q
    st.session_state.run = True


def _submit() -> None:
    st.session_state.run = True


def show(d: client.Display) -> None:
    if d.message:
        getattr(st, d.kind if d.kind in ("success", "info", "warning", "error") else "info")(d.message)
    if d.answer:
        st.markdown(d.answer)
    if d.sql:
        with st.expander("SQL"):
            st.code(d.sql, language="sql")
    if d.rows:
        try:
            df = pd.DataFrame(d.rows, columns=d.columns or None)
        except ValueError:
            df = pd.DataFrame(d.rows)
        st.dataframe(df, hide_index=True)
    if d.chart_url:
        png = client.fetch_chart(d.chart_url)
        if png:
            st.image(png)
        else:
            st.caption("The chart could not be loaded.")
    if d.caption:
        st.caption(d.caption)


st.title("AI Analyst Agent")
st.write("Ask business questions about the UCI Online Retail II dataset. "
         "The agent writes read-only SQL, draws charts and segments customers.")

cols = st.columns(len(EXAMPLES))
for col, q in zip(cols, EXAMPLES):
    col.button(q, on_click=_use_example, args=(q,), width="stretch")

st.text_input("Your question", key="question", max_chars=500, on_change=_submit)
st.button("Ask", type="primary", on_click=_submit)

if st.session_state.run:
    st.session_state.run = False
    question = st.session_state.question.strip()
    if question:
        with st.spinner("Thinking... this can take up to a couple of minutes."):
            display = client.ask(question)
        st.session_state.history.insert(0, (question, display))
        del st.session_state.history[MAX_HISTORY:]
    else:
        st.warning("Type a question first.")

if st.session_state.history:
    question, display = st.session_state.history[0]
    st.subheader(question)
    show(display)

    if len(st.session_state.history) > 1:
        with st.expander("Session history", expanded=False):
            for question, display in st.session_state.history[1:]:
                st.markdown(f"**{question}**")
                st.write(display.answer or display.message)
                st.divider()
