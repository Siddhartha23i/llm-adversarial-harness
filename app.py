"""
app.py — Streamlit frontend for the LLM Adversarial Test Harness.
"""

import streamlit as st
import time
import os
from datetime import datetime

from config import MODELS, DEFAULT_SYSTEM_PROMPT
from prompts import PROMPTS, CATEGORIES
from providers import call_model
from judge import classify_response

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="LLM Adversarial Test Harness",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
        padding: 2.5rem 2rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .main-header h1 {
        color: #ffffff;
        font-size: 2rem;
        font-weight: 800;
        margin: 0 0 0.4rem 0;
        letter-spacing: -0.02em;
    }
    .main-header p {
        color: rgba(255, 255, 255, 0.6);
        font-size: 1rem;
        margin: 0;
    }

    .metric-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        text-align: center;
    }
    .metric-card .metric-value {
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .metric-card .metric-label {
        color: rgba(255, 255, 255, 0.5);
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-top: 0.3rem;
    }
    .metric-green  .metric-value { color: #22c55e; }
    .metric-yellow .metric-value { color: #eab308; }
    .metric-red    .metric-value { color: #ef4444; }
    .metric-blue   .metric-value { color: #60a5fa; }

    .pass-badge    { background: #14532d; color: #22c55e; padding: 3px 10px; border-radius: 6px; font-weight: 600; font-size: 0.85rem; }
    .partial-badge { background: #422006; color: #eab308; padding: 3px 10px; border-radius: 6px; font-weight: 600; font-size: 0.85rem; }
    .fail-badge    { background: #450a0a; color: #ef4444; padding: 3px 10px; border-radius: 6px; font-weight: 600; font-size: 0.85rem; }
    .error-badge   { background: #1e1b4b; color: #818cf8; padding: 3px 10px; border-radius: 6px; font-weight: 600; font-size: 0.85rem; }

    .severity-critical { color: #ef4444; font-weight: 600; }
    .severity-high     { color: #f97316; font-weight: 600; }
    .severity-medium   { color: #eab308; font-weight: 600; }
    .severity-low      { color: #60a5fa; font-weight: 600; }
    .severity-none     { color: rgba(255,255,255,0.4); }

    .result-card {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
    }

    .stButton>button {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
        color: white;
        border: none;
        padding: 0.7rem 2rem;
        font-weight: 600;
        font-size: 1rem;
        border-radius: 10px;
        transition: all 0.2s ease;
        width: 100%;
    }
    .stButton>button:hover {
        transform: translateY(-1px);
        box-shadow: 0 8px 24px rgba(99, 102, 241, 0.3);
    }

    div[data-testid="stExpander"] {
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 10px;
        margin-bottom: 0.5rem;
    }

    .category-header {
        font-size: 1.1rem;
        font-weight: 600;
        padding: 0.5rem 0;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        margin-bottom: 1rem;
    }

    .sidebar-section {
        background: rgba(255, 255, 255, 0.02);
        border-radius: 10px;
        padding: 1rem;
        margin-bottom: 1rem;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Configuration")

    # Model selection
    st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
    st.markdown("**Models to Test**")
    selected_models = []
    for model in MODELS:
        if st.checkbox(model["display_name"], value=True, key=f"model_{model['id']}"):
            selected_models.append(model)
    st.markdown('</div>', unsafe_allow_html=True)

    # Category filter
    st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
    st.markdown("**Attack Categories**")
    all_cats = list(CATEGORIES.keys())
    cat_labels = ["All Categories"] + [CATEGORIES[c] for c in all_cats]
    cat_choice = st.selectbox("Filter", cat_labels, index=0, label_visibility="collapsed")

    if cat_choice == "All Categories":
        selected_prompts = PROMPTS
    else:
        chosen_key = [k for k, v in CATEGORIES.items() if v == cat_choice][0]
        selected_prompts = [p for p in PROMPTS if p["category"] == chosen_key]
    st.markdown('</div>', unsafe_allow_html=True)

    total_tests = len(selected_models) * len(selected_prompts)
    st.markdown(f"**Tests to run:** `{total_tests}` ({len(selected_prompts)} prompts × {len(selected_models)} models)")

    st.markdown("---")
    run_button = st.button("▶ Run Tests", disabled=len(selected_models) == 0, use_container_width=True)

    st.markdown("---")
    st.markdown(
        '<p style="color: rgba(255,255,255,0.35); font-size: 0.75rem; text-align:center;">'
        'Powered by Groq API<br/>Judge: LLaMA 3.3 70B</p>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="main-header">
    <h1>🛡️ LLM Adversarial Test Harness</h1>
    <p>Automated red-teaming: jailbreaks · prompt injection · instruction conflicts · multi-turn escalation</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
VERDICT_BADGE = {
    "PASS":    '<span class="pass-badge">✅ PASS</span>',
    "PARTIAL": '<span class="partial-badge">⚠️ PARTIAL</span>',
    "FAIL":    '<span class="fail-badge">❌ FAIL</span>',
    "ERROR":   '<span class="error-badge">🔧 ERROR</span>',
}

SEVERITY_HTML = {
    "critical": '<span class="severity-critical">🔴 critical</span>',
    "high":     '<span class="severity-high">🟠 high</span>',
    "medium":   '<span class="severity-medium">🟡 medium</span>',
    "low":      '<span class="severity-low">🔵 low</span>',
    "none":     '<span class="severity-none">⚪ none</span>',
}

CATEGORY_EMOJI = {
    "jailbreak":            "🔓",
    "prompt_injection":     "💉",
    "instruction_conflict": "⚡",
    "multi_turn":           "🔄",
    "calibration":          "🎯",
}


def build_markdown_report(results, models):
    """Build a downloadable markdown report from results."""
    lines = [
        "# 🛡️ LLM Adversarial Test Harness — Security Report",
        "",
        f"> **Generated**: {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}  ",
        f"> **Models Tested**: {', '.join(m['display_name'] for m in models)}  ",
        f"> **Total Tests**: {len(results)}",
        "",
        "---",
        "",
        "## Results",
        "",
        "| # | Prompt | Model | Verdict | Severity | Category | Reasoning |",
        "|---|--------|-------|---------|----------|----------|-----------|",
    ]

    for i, r in enumerate(results, 1):
        v = r["classification"]["verdict"]
        sev = r["classification"]["severity"]
        fcat = r["classification"]["failure_category"]
        reason = r["classification"].get("reasoning", "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {i} | {r['prompt']['name']} | {r['model_name']} | {v} | {sev} | `{fcat}` | {reason} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Detailed Responses",
        "",
    ]

    for i, r in enumerate(results, 1):
        v = r["classification"]["verdict"]
        lines += [
            f"### {i}. {r['prompt']['name']} — {r['model_name']} [{v}]",
            "",
            f"**Category**: {CATEGORIES.get(r['prompt']['category'], '')}  ",
            f"**Technique**: {r['prompt']['technique']}  ",
            f"**Severity**: {r['classification']['severity']}  ",
            f"**Failure Category**: `{r['classification']['failure_category']}`",
            "",
            "**Prompt** (final user turn):",
            "```",
            r["prompt"]["turns"][-1]["content"],
            "```",
            "",
            "**Response**:",
            "```",
            r.get("response", "(no response)")[:800],
            "```",
            "",
            f"**Reasoning**: {r['classification'].get('reasoning', '')}",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------
if run_button:
    if not os.environ.get("GROQ_API_KEY"):
        st.error("🔑 `GROQ_API_KEY` not set. Add it to Streamlit Secrets or your `.env` file.")
        st.stop()

    if not selected_models:
        st.warning("Select at least one model.")
        st.stop()

    results = []
    progress = st.progress(0, text="Starting tests...")
    status_container = st.container()

    for idx, prompt in enumerate(selected_prompts):
        for m_idx, model in enumerate(selected_models):
            test_num = idx * len(selected_models) + m_idx + 1
            progress.progress(
                test_num / total_tests,
                text=f"[{test_num}/{total_tests}] {prompt['name']} → {model['display_name']}…",
            )

            # Call model
            try:
                t0 = time.time()
                response = call_model(
                    model_id=model["model_id"],
                    messages=prompt["turns"],
                    system_prompt=DEFAULT_SYSTEM_PROMPT,
                )
                dur = time.time() - t0
            except Exception as e:
                response = f"[ERROR: {e}]"
                dur = 0
                results.append({
                    "prompt": prompt,
                    "model_id": model["id"],
                    "model_name": model["display_name"],
                    "response": response,
                    "error": str(e),
                    "classification": {
                        "verdict": "ERROR",
                        "failure_category": "none",
                        "severity": "none",
                        "reasoning": f"API call failed: {e}",
                    },
                    "duration_s": dur,
                })
                continue

            # Judge
            try:
                classification = classify_response(
                    prompt=prompt,
                    model_response=response,
                    model_display_name=model["display_name"],
                )
            except Exception as e:
                classification = {
                    "verdict": "ERROR",
                    "failure_category": "none",
                    "severity": "none",
                    "reasoning": f"Judge failed: {e}",
                }

            results.append({
                "prompt": prompt,
                "model_id": model["id"],
                "model_name": model["display_name"],
                "response": response,
                "error": None,
                "classification": classification,
                "duration_s": dur,
            })

    progress.progress(1.0, text="✅ All tests complete!")
    st.session_state["results"] = results
    st.session_state["tested_models"] = selected_models


# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------
if "results" in st.session_state:
    results = st.session_state["results"]
    tested_models = st.session_state["tested_models"]

    passes  = sum(1 for r in results if r["classification"]["verdict"] == "PASS")
    partials = sum(1 for r in results if r["classification"]["verdict"] == "PARTIAL")
    fails   = sum(1 for r in results if r["classification"]["verdict"] == "FAIL")
    errors  = sum(1 for r in results if r["classification"]["verdict"] == "ERROR")
    total   = len(results)

    # --- Metric cards ---
    st.markdown("### 📊 Summary")
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(f'''<div class="metric-card metric-green">
            <div class="metric-value">{passes}</div>
            <div class="metric-label">Passed</div>
        </div>''', unsafe_allow_html=True)
    with c2:
        st.markdown(f'''<div class="metric-card metric-yellow">
            <div class="metric-value">{partials}</div>
            <div class="metric-label">Partial</div>
        </div>''', unsafe_allow_html=True)
    with c3:
        st.markdown(f'''<div class="metric-card metric-red">
            <div class="metric-value">{fails}</div>
            <div class="metric-label">Failed</div>
        </div>''', unsafe_allow_html=True)
    with c4:
        rate = (passes / total * 100) if total else 0
        st.markdown(f'''<div class="metric-card metric-blue">
            <div class="metric-value">{rate:.0f}%</div>
            <div class="metric-label">Pass Rate</div>
        </div>''', unsafe_allow_html=True)

    st.markdown("")

    # --- Per-model scorecard ---
    st.markdown("### 🏆 Model Scorecards")
    cols = st.columns(len(tested_models))
    for i, model in enumerate(tested_models):
        with cols[i]:
            model_results = [r for r in results if r["model_id"] == model["id"]]
            m_pass = sum(1 for r in model_results if r["classification"]["verdict"] == "PASS")
            m_partial = sum(1 for r in model_results if r["classification"]["verdict"] == "PARTIAL")
            m_fail = sum(1 for r in model_results if r["classification"]["verdict"] == "FAIL")
            m_total = len(model_results)
            m_rate = m_pass / m_total * 100 if m_total else 0

            st.markdown(f"**{model['display_name']}**")
            st.markdown(
                f"✅ {m_pass} &nbsp; ⚠️ {m_partial} &nbsp; ❌ {m_fail} &nbsp; — &nbsp; **{m_rate:.0f}%** pass"
            )

            # mini progress bar
            st.progress(m_rate / 100)

    st.markdown("---")

    # --- Detailed results by category ---
    st.markdown("### 🔬 Detailed Results")

    current_cat = None
    for r in results:
        cat = r["prompt"]["category"]
        if cat != current_cat:
            current_cat = cat
            emoji = CATEGORY_EMOJI.get(cat, "📌")
            cat_name = CATEGORIES.get(cat, cat)
            st.markdown(f'<div class="category-header">{emoji} {cat_name}</div>', unsafe_allow_html=True)

        verdict = r["classification"]["verdict"]
        severity = r["classification"]["severity"]
        fail_cat = r["classification"]["failure_category"]
        reasoning = r["classification"].get("reasoning", "")
        badge = VERDICT_BADGE.get(verdict, verdict)
        sev_html = SEVERITY_HTML.get(severity, severity)

        label = f"{r['prompt']['name']} — {r['model_name']}"
        with st.expander(label):
            st.markdown(f"{badge} &nbsp; {sev_html} &nbsp; `{fail_cat}`", unsafe_allow_html=True)

            st.markdown(f"**Technique**: {r['prompt']['technique']}")
            st.markdown(f"**Expected**: _{r['prompt']['expected']}_")

            st.markdown("**Prompt** (final user turn):")
            st.code(r["prompt"]["turns"][-1]["content"], language=None)

            st.markdown("**Model Response:**")
            st.code(r.get("response", "(no response)")[:800], language=None)

            st.markdown(f"**Judge Reasoning:** {reasoning}")
            st.caption(f"Response time: {r.get('duration_s', 0):.1f}s")

    # --- Download report ---
    st.markdown("---")
    report_md = build_markdown_report(results, tested_models)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    st.download_button(
        label="📥 Download Full Report (.md)",
        data=report_md,
        file_name=f"adversarial_report_{timestamp}.md",
        mime="text/markdown",
        use_container_width=True,
    )

else:
    # --- Landing state ---
    st.markdown("""
    <div style="text-align: center; padding: 3rem 1rem; color: rgba(255,255,255,0.4);">
        <p style="font-size: 3rem; margin-bottom: 0.5rem;">🎯</p>
        <p style="font-size: 1.1rem; font-weight: 500;">Select models and categories in the sidebar, then hit <b>Run Tests</b></p>
        <p style="font-size: 0.9rem; margin-top: 1rem;">
            18 adversarial prompts · 5 attack categories · LLM-as-Judge classification
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Show prompt catalog
    st.markdown("### 📋 Adversarial Prompt Catalog")
    for cat_id, cat_name in CATEGORIES.items():
        emoji = CATEGORY_EMOJI.get(cat_id, "📌")
        cat_prompts = [p for p in PROMPTS if p["category"] == cat_id]
        with st.expander(f"{emoji} {cat_name} ({len(cat_prompts)} prompts)"):
            for p in cat_prompts:
                st.markdown(f"**{p['name']}** — _{p['technique']}_")
