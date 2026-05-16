"""Exercise 5 — Streamlit approval UI for the HITL PR review agent.

Run with:
    uv run streamlit run app.py

Goal: wrap the LangGraph built in exercises 1–4 in a web UI that adapts to
the confidence bucket of each PR.

Routing thresholds (common/schemas.py):
    > 72%        auto_approve     UI shows a success card; reviewer does nothing
    58 – 72%     human_approval   UI shows Approve / Reject / Edit buttons
    <  58%       escalate         UI shows a question form for the reviewer
"""

from __future__ import annotations

import asyncio
import uuid

import aiosqlite
import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from common.db import checkpoint_db_path, db_conn
from exercises.exercise_4_audit import build_graph


load_dotenv()


# ─── Session state ─────────────────────────────────────────────────────────
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "pr_url" not in st.session_state:
    st.session_state.pr_url = ""
if "interrupt_payload" not in st.session_state:
    st.session_state.interrupt_payload = None
if "final" not in st.session_state:
    st.session_state.final = None


# ─── Page setup ────────────────────────────────────────────────────────────
st.set_page_config(page_title="HITL PR Review", layout="wide")
st.title("HITL PR Review Agent")


# ─── Sidebar — recent sessions ─────────────────────────────────────────────
with st.sidebar:
    st.header("Recent sessions")

    async def _recent_sessions() -> list[dict]:
        async with db_conn() as conn:
            async with conn.execute(
                """
                SELECT thread_id,
                       pr_url,
                       MAX(timestamp) AS last_event,
                       CASE
                           WHEN MAX(CASE WHEN risk_level = 'high' THEN 3 WHEN risk_level = 'med' THEN 2 ELSE 1 END) = 3 THEN 'high'
                           WHEN MAX(CASE WHEN risk_level = 'high' THEN 3 WHEN risk_level = 'med' THEN 2 ELSE 1 END) = 2 THEN 'med'
                           ELSE 'low'
                       END AS worst_risk
                  FROM audit_events
                 GROUP BY thread_id, pr_url
                 ORDER BY MAX(timestamp) DESC
                 LIMIT 10
                """
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    sessions = asyncio.run(_recent_sessions())
    if not sessions:
        st.caption("No recent sessions yet.")
    for row in sessions:
        label = f"{row['worst_risk']} | {row['pr_url'].rsplit('/', 1)[-1]} | {row['last_event']}"
        if st.button(label, key=f"session_{row['thread_id']}"):
            state = asyncio.run(load_session_state(row["thread_id"]))
            values = state.values if getattr(state, "values", None) else {}
            st.session_state.thread_id = row["thread_id"]
            st.session_state.pr_url = values.get("pr_url", row["pr_url"])
            st.session_state.interrupt_payload = None
            st.session_state.final = None
            if getattr(state, "interrupts", None):
                st.session_state.interrupt_payload = state.interrupts[0].value
            elif values:
                st.session_state.final = values
            st.rerun()


# ─── Top form — start a new review ─────────────────────────────────────────
with st.form("start"):
    pr_url = st.text_input(
        "PR URL", value=st.session_state.pr_url,
        placeholder="https://github.com/VinUni-AI20k/PR-Demo/pull/1",
    )
    submitted = st.form_submit_button("Run review")


# ─── Renderers per interrupt kind ──────────────────────────────────────────
def render_approval_card(payload: dict) -> dict | None:
    """58–72% bucket: show the LLM review + 3 buttons. Return resume dict or None."""
    conf = payload["confidence"]
    st.subheader(f"Approval requested — confidence {conf:.0%}")
    st.caption(payload["confidence_reasoning"])
    st.markdown(payload["summary"])

    for c in payload.get("comments", []):
        st.markdown(f"- **[{c['severity']}]** `{c['file']}:{c.get('line') or '?'}` — {c['body']}")

    with st.expander("Diff"):
        st.code(payload.get("diff_preview", ""), language="diff")

    feedback = st.text_input("Feedback (optional)", key="approval_feedback")
    col1, col2, col3 = st.columns(3)
    if col1.button("Approve", type="primary"):
        return {"choice": "approve", "feedback": feedback}
    if col2.button("Reject"):
        return {"choice": "reject", "feedback": feedback}
    if col3.button("Edit"):
        return {"choice": "edit", "feedback": feedback}
    return None


def render_escalation_card(payload: dict) -> dict | None:
    """< 58% bucket: show risk factors + question form. Return {question: answer} or None."""
    conf = payload["confidence"]
    st.subheader(f"Strong escalation — confidence {conf:.0%}")
    st.caption(payload["confidence_reasoning"])
    if payload.get("risk_factors"):
        st.error("Risks: " + ", ".join(payload["risk_factors"]))
    st.markdown(payload["summary"])

    with st.form("escalation"):
        answers: dict[str, str] = {}
        for idx, question in enumerate(payload.get("questions", [])):
            answers[question] = st.text_input(question, key=f"escalation_{idx}")
        submitted = st.form_submit_button("Submit answers")
        if submitted:
            return answers
    return None


# ─── Drive the graph ───────────────────────────────────────────────────────
async def run_graph(pr_url: str, thread_id: str, resume_value=None):
    """Invoke the graph once. Returns the final result or {'__interrupt__': ...}."""
    async with aiosqlite.connect(checkpoint_db_path()) as conn:
        await conn.execute("PRAGMA journal_mode=MEMORY")
        await conn.execute("PRAGMA synchronous=NORMAL")
        cp = AsyncSqliteSaver(conn)
        await cp.setup()
        app = build_graph(cp)
        cfg = {"configurable": {"thread_id": thread_id}}

        if resume_value is None:
            return await app.ainvoke({"pr_url": pr_url, "thread_id": thread_id}, cfg)
        return await app.ainvoke(Command(resume=resume_value), cfg)


async def load_session_state(thread_id: str):
    """Load the latest persisted state for an existing thread."""
    async with aiosqlite.connect(checkpoint_db_path()) as conn:
        await conn.execute("PRAGMA journal_mode=MEMORY")
        await conn.execute("PRAGMA synchronous=NORMAL")
        cp = AsyncSqliteSaver(conn)
        await cp.setup()
        app = build_graph(cp)
        cfg = {"configurable": {"thread_id": thread_id}}
        return await app.aget_state(cfg)


# ─── Main flow ─────────────────────────────────────────────────────────────
if submitted and pr_url:
    st.session_state.pr_url = pr_url
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.interrupt_payload = None
    st.session_state.final = None

    with st.spinner("Fetching PR + asking the LLM..."):
        result = asyncio.run(run_graph(pr_url, st.session_state.thread_id))

    if "__interrupt__" in result:
        st.session_state.interrupt_payload = result["__interrupt__"][0].value
    else:
        st.session_state.final = result

# Render the current interrupt card, if any
payload = st.session_state.interrupt_payload
if payload is not None:
    kind = payload["kind"]
    answer = render_approval_card(payload) if kind == "approval_request" else render_escalation_card(payload)
    if answer is not None:
        with st.spinner("Resuming..."):
            result = asyncio.run(run_graph(
                st.session_state.pr_url, st.session_state.thread_id, resume_value=answer,
            ))
        if "__interrupt__" in result:
            st.session_state.interrupt_payload = result["__interrupt__"][0].value
        else:
            st.session_state.interrupt_payload = None
            st.session_state.final = result
        st.rerun()

# Render final state, if reached
if st.session_state.final is not None:
    final = st.session_state.final
    action = final.get("final_action", "?")
    if action.startswith("auto") or action.startswith("committed"):
        st.success(f"✓ {action} — comment posted to {st.session_state.pr_url}")
    elif action == "rejected":
        st.warning("Rejected — no comment posted")
    else:
        st.info(f"final_action = {action}")
    st.caption(f"thread_id = {st.session_state.thread_id}  ·  replay: "
               f"`uv run python -m audit.replay --thread {st.session_state.thread_id}`")
