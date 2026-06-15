"""
app.py — KI-Co-Analyst · Investment Bank Interface
Berner Fachhochschule | Bachelor Thesis 2025/26 | Luca Lüdi

Start: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import json
import os
import sys
import hashlib
import time
from datetime import datetime
from pathlib import Path
import subprocess
import tempfile

try:
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

from tools.finance_tools import search_ticker

# ══════════════════════════════════════════════════════════════════════════════
# CREDENTIALS  (in production: move to .env / secrets.toml)
# Format: { "username": "sha256_hash_of_password" }
# Standardpasswort für "admin" ist "analyst2025" — ändere es in settings.json
# ══════════════════════════════════════════════════════════════════════════════

CREDENTIALS_FILE = "credentials.json"
_DEFAULT_CREDENTIALS = {
    "admin": hashlib.sha256("analyst2025".encode()).hexdigest(),
}

def _load_credentials() -> dict:
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return _DEFAULT_CREDENTIALS

def _save_credentials(creds: dict):
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2)

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _verify(username: str, password: str) -> bool:
    creds = _load_credentials()
    return creds.get(username) == _hash(password)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="KI-Co-Analyst · Research Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
# DESIGN TOKENS & CSS
# ══════════════════════════════════════════════════════════════════════════════

NAVY   = "#0a1628"
BLUE   = "#1a2f45"
GOLD   = "#c9a84c"
GOLD_L = "#e8c97a"
WHITE  = "#ffffff"
OFF_W  = "#f7f8fa"
GRAY_L = "#e9ecef"
GRAY   = "#8a9bb0"
GREEN  = "#1e7c45"
RED    = "#b92d2d"
AMBER  = "#9a6e00"

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&family=Inter:wght@300;400;500;600&display=swap');

  html, body, [class*="css"] {{
    font-family: 'Inter', -apple-system, sans-serif;
    background: {OFF_W};
  }}

  /* ── Scrollbar ── */
  ::-webkit-scrollbar {{ width: 5px; }}
  ::-webkit-scrollbar-track {{ background: {OFF_W}; }}
  ::-webkit-scrollbar-thumb {{ background: {GRAY}; border-radius: 3px; }}

  /* ── Topbar ── */
  .topbar {{
    background: {NAVY};
    border-bottom: 1px solid {GOLD}44;
    padding: 0.8rem 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 999;
    margin: -1rem -1rem 1.5rem -1rem;
  }}
  .topbar-brand {{
    font-family: 'Playfair Display', serif;
    color: {WHITE};
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: -0.3px;
  }}
  .topbar-brand span {{ color: {GOLD}; }}
  .topbar-meta {{
    font-size: 0.8rem;
    color: {GRAY};
    letter-spacing: 0.05em;
  }}

  /* ── Sidebar ── */
  section[data-testid="stSidebar"] {{
    background: {NAVY} !important;
    border-right: 1px solid {GOLD}22;
  }}
  section[data-testid="stSidebar"] * {{
    color: {WHITE} !important;
  }}
  section[data-testid="stSidebar"] .stTextInput input {{
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    color: {WHITE} !important;
    border-radius: 6px;
  }}
  section[data-testid="stSidebar"] .stTextInput input::placeholder {{
    color: {GRAY} !important;
  }}
  section[data-testid="stSidebar"] hr {{
    border-color: rgba(255,255,255,0.1) !important;
  }}

  /* ── Nav buttons in sidebar ── */
  .nav-btn {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.65rem 1rem;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s ease;
    font-size: 0.9rem;
    font-weight: 500;
    color: rgba(255,255,255,0.7);
    text-decoration: none;
    margin-bottom: 2px;
  }}
  .nav-btn:hover {{ background: rgba(255,255,255,0.08); color: {WHITE}; }}
  .nav-btn.active {{ background: {GOLD}22; color: {GOLD}; border-left: 3px solid {GOLD}; }}
  .nav-icon {{ font-size: 1rem; width: 1.2rem; text-align: center; }}

  /* ── Login ── */
  .login-wrap {{
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 70vh;
    padding: 2rem;
  }}
  .login-card {{
    background: {WHITE};
    border: 1px solid {GRAY_L};
    border-radius: 16px;
    padding: 3rem 2.5rem;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 8px 40px rgba(0,0,0,0.08);
  }}
  .login-logo {{
    text-align: center;
    margin-bottom: 2rem;
  }}
  .login-logo-text {{
    font-family: 'Playfair Display', serif;
    font-size: 1.8rem;
    font-weight: 700;
    color: {NAVY};
  }}
  .login-logo-text span {{ color: {GOLD}; }}
  .login-subtitle {{
    font-size: 0.82rem;
    color: {GRAY};
    text-align: center;
    margin-top: 0.25rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }}

  /* ── Cards ── */
  .card {{
    background: {WHITE};
    border: 1px solid {GRAY_L};
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    height: 100%;
  }}
  .card-accent {{
    border-left: 3px solid {GOLD};
  }}
  .card-title {{
    font-size: 0.72rem;
    font-weight: 600;
    color: {GRAY};
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.5rem;
  }}
  .card-value {{
    font-family: 'Playfair Display', serif;
    font-size: 2rem;
    font-weight: 700;
    color: {NAVY};
    line-height: 1.1;
  }}
  .card-sub {{
    font-size: 0.8rem;
    color: {GRAY};
    margin-top: 0.3rem;
  }}

  /* ── Hero (Homepage) ── */
  .hero {{
    background: linear-gradient(135deg, {NAVY} 0%, #1a2f45 60%, #0f2030 100%);
    border-radius: 16px;
    padding: 3.5rem 3rem;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content: '';
    position: absolute;
    top: -50%;
    right: -10%;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, {GOLD}15 0%, transparent 70%);
    pointer-events: none;
  }}
  .hero-eyebrow {{
    font-size: 0.75rem;
    font-weight: 600;
    color: {GOLD};
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 0.8rem;
  }}
  .hero-title {{
    font-family: 'Playfair Display', serif;
    font-size: 2.4rem;
    font-weight: 700;
    color: {WHITE};
    line-height: 1.2;
    margin-bottom: 1rem;
  }}
  .hero-subtitle {{
    font-size: 1rem;
    color: rgba(255,255,255,0.65);
    line-height: 1.7;
    max-width: 520px;
  }}

  /* ── Section header ── */
  .section-head {{
    font-family: 'Playfair Display', serif;
    font-size: 1.1rem;
    font-weight: 600;
    color: {NAVY};
    border-bottom: 2px solid {GOLD};
    padding-bottom: 0.4rem;
    margin: 1.8rem 0 1rem 0;
  }}

  /* ── Badges ── */
  .badge {{
    display: inline-block;
    padding: 0.3rem 1rem;
    border-radius: 20px;
    font-weight: 600;
    font-size: 0.85rem;
    letter-spacing: 0.05em;
  }}
  .badge-green  {{ background: #e6f9ee; color: {GREEN}; border: 1px solid {GREEN}44; }}
  .badge-amber  {{ background: #fef9e7; color: {AMBER}; border: 1px solid {AMBER}44; }}
  .badge-red    {{ background: #fdecec; color: {RED};   border: 1px solid {RED}44; }}
  .badge-blue   {{ background: #eaf1fb; color: #1a4d8f; border: 1px solid #1a4d8f44; }}
  .badge-orange {{ background: #fef3e7; color: #8a4500; border: 1px solid #8a450044; }}

  /* ── History card ── */
  .hist-card {{
    background: {WHITE};
    border: 1px solid {GRAY_L};
    border-radius: 10px;
    padding: 1rem 1.25rem;
    margin-bottom: 0.6rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    transition: box-shadow 0.15s;
  }}
  .hist-card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.08); }}
  .hist-ticker {{
    font-family: 'Playfair Display', serif;
    font-size: 1.1rem;
    font-weight: 700;
    color: {NAVY};
  }}
  .hist-company {{
    font-size: 0.82rem;
    color: {GRAY};
    margin-top: 1px;
  }}
  .hist-date {{
    font-size: 0.78rem;
    color: {GRAY};
    text-align: right;
  }}

  /* ── Upside ── */
  .up   {{ color: {GREEN}; font-weight: 600; }}
  .down {{ color: {RED};   font-weight: 600; }}

  /* ── Investment case bullet ── */
  .ic-bullet {{
    background: {OFF_W};
    border-left: 3px solid {GOLD};
    padding: 0.7rem 1rem;
    margin-bottom: 0.5rem;
    border-radius: 0 6px 6px 0;
    font-size: 0.88rem;
    line-height: 1.6;
    color: #2c3e50;
  }}

  /* ── Scenario cards ── */
  .sc-bear {{ background:#fff5f5; border:1px solid #fca5a5; border-radius:10px; padding:1.2rem; }}
  .sc-base {{ background:#fffbeb; border:1px solid #fcd34d; border-radius:10px; padding:1.2rem; }}
  .sc-bull {{ background:#f0fdf4; border:1px solid #86efac; border-radius:10px; padding:1.2rem; }}

  /* ── Conviction killer ── */
  .ck-box {{
    background: #fff5f5;
    border: 1px solid #fca5a5;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.6rem;
  }}

  /* ── Footer ── */
  .footer {{
    text-align: center;
    font-size: 0.75rem;
    color: {GRAY};
    padding: 2rem 0 0.5rem 0;
    border-top: 1px solid {GRAY_L};
    margin-top: 3rem;
  }}

  /* ── Hide Streamlit chrome ── */
  #MainMenu {{visibility:hidden;}}
  footer {{visibility:hidden;}}
  .stDeployButton {{display:none;}}
  .block-container {{padding-top:1rem;}}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _parse_num(val):
    if isinstance(val, (int, float)): return float(val)
    if not isinstance(val, str): return None
    import re
    m = re.search(r"-?\d+[.,]?\d*", val.replace(",", "."))
    return float(m.group()) if m else None

def safe_num(v, fmt="{:.2f}", fallback="-"):
    try: return fmt.format(float(v))
    except: return fallback

def badge_rec(rec: str) -> str:
    r = (rec or "").upper()
    cls = ("badge-green" if r in ("KAUFEN", "ÜBERGEWICHTEN")
           else "badge-red" if r in ("VERKAUFEN", "UNTERGEWICHTEN")
           else "badge-amber")
    return f'<span class="badge {cls}">{r}</span>'

def upside_html(v) -> str:
    try:
        f = float(v)
        if f > 0: return f'<span class="up">▲ +{f:.1f}%</span>'
        return f'<span class="down">▼ {f:.1f}%</span>'
    except: return "-"

def ampel_icon(signal: str) -> str:
    s = (signal or "").lower()
    if "positiv" in s or "tailwind" in s: return "🟢"
    if "negativ" in s or "headwind" in s: return "🔴"
    return "🟡"


# ══════════════════════════════════════════════════════════════════════════════
# HISTORY  (in ./history/ als JSON gespeichert)
# ══════════════════════════════════════════════════════════════════════════════

HISTORY_DIR = Path("history")
HISTORY_DIR.mkdir(exist_ok=True)

def save_to_history(data: dict):
    ticker = data.get("ticker", "UNKNOWN")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = HISTORY_DIR / f"{ticker}_{ts}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

def load_history() -> list[dict]:
    entries = []
    for fp in sorted(HISTORY_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            d["_file"] = str(fp)
            entries.append(d)
        except Exception:
            pass
    return entries


# ══════════════════════════════════════════════════════════════════════════════
# CHARTS
# ══════════════════════════════════════════════════════════════════════════════

def chart_scenarios(scenarios, ccy, current_price=None):
    if not _PLOTLY or not scenarios: return None
    names, targets, probs, colors = [], [], [], []
    cmap = {"Bear Case": RED, "Base Case": "#2e6fb0", "Bull Case": GREEN}
    for s in scenarios:
        nm = s.get("name","") if isinstance(s,dict) else getattr(s,"name","")
        pt = _parse_num(s.get("price_target") if isinstance(s,dict) else getattr(s,"price_target",None))
        pr = s.get("probability_pct") if isinstance(s,dict) else getattr(s,"probability_pct",None)
        if pt is None: continue
        names.append(nm); targets.append(pt); probs.append(pr)
        colors.append(cmap.get(nm, "#2e6fb0"))
    if not targets: return None
    text = [f"{ccy} {t:.2f}<br>{p}%" if p else f"{ccy} {t:.2f}" for t,p in zip(targets,probs)]
    fig = go.Figure(go.Bar(x=names,y=targets,text=text,textposition="outside",
                           marker_color=colors,width=0.5))
    if current_price:
        fig.add_hline(y=current_price,line_dash="dash",line_color=NAVY,
                      annotation_text=f"Kurs {ccy} {current_price:.2f}",
                      annotation_position="top left")
    fig.update_layout(height=320,margin=dict(t=40,b=20,l=20,r=20),
                      plot_bgcolor="white",showlegend=False,
                      yaxis_title=f"Kursziel ({ccy})",
                      font=dict(family="Inter"))
    return fig

def chart_margin_trend(rows):
    if not _PLOTLY or not rows: return None
    years, margins, is_est = [], [], []
    for r in rows:
        y = r.get("year","") if isinstance(r,dict) else ""
        m = _parse_num(r.get("ebitda_margin_pct") if isinstance(r,dict) else None)
        if y and m is not None:
            years.append(y); margins.append(m)
            is_est.append((r.get("type")=="E") if isinstance(r,dict) else False)
    if len(years) < 2: return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years,y=margins,mode="lines+markers+text",
        text=[f"{m:.1f}%" for m in margins],textposition="top center",
        line=dict(color="#2e6fb0",width=2.5),
        marker=dict(size=8,color=[GREEN if e else "#2e6fb0" for e in is_est]),
    ))
    fig.update_layout(height=300,margin=dict(t=30,b=20,l=20,r=20),
                      plot_bgcolor="white",showlegend=False,
                      yaxis_title="EBITDA-Marge (%)",
                      font=dict(family="Inter"))
    return fig

def chart_valuation(vt):
    if not _PLOTLY or not vt: return None
    metrics,cur,peer,hist = [],[],[],[]
    for r in vt:
        if not isinstance(r,dict): continue
        c = _parse_num(r.get("current_value"))
        if c is None: continue
        metrics.append(r.get("metric",""))
        cur.append(c)
        peer.append(_parse_num(r.get("peer_average")))
        hist.append(_parse_num(r.get("historical_average")))
    if not metrics: return None
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Aktuell",x=metrics,y=cur,marker_color="#2e6fb0"))
    fig.add_trace(go.Bar(name="Peer Ø",x=metrics,y=peer,marker_color="#9bb4cc"))
    fig.add_trace(go.Bar(name="Hist. Ø",x=metrics,y=hist,marker_color="#cbb994"))
    fig.update_layout(height=340,margin=dict(t=30,b=20,l=20,r=20),
                      plot_bgcolor="white",barmode="group",
                      legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
                      font=dict(family="Inter"))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# NODE.JS WORD EXPORT
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_resource
def ensure_node_deps():
    try:
        r = subprocess.run(["node","--version"],capture_output=True,text=True,timeout=10)
        if r.returncode != 0: return False,"Node.js fehlt"
        if not os.path.exists("node_modules/docx"):
            ins = subprocess.run(["npm","install","docx","--no-audit","--no-fund"],
                                 capture_output=True,text=True,timeout=120)
            if ins.returncode != 0: return False,f"npm: {ins.stderr[:100]}"
        return True,"OK"
    except Exception as e: return False,str(e)

def generate_word_memo(data: dict) -> bytes | None:
    if not os.path.exists("export_memo.js"): return None
    with tempfile.NamedTemporaryFile(suffix=".docx",delete=False) as tmp:
        out = tmp.name
    try:
        r = subprocess.run(["node","export_memo.js","-",out],
                           input=json.dumps(data,default=str,ensure_ascii=False),
                           capture_output=True,text=True,timeout=30,encoding="utf-8")
        if r.returncode != 0:
            st.error(f"Word-Export: {r.stderr[:200]}")
            return None
        with open(out,"rb") as f: return f.read()
    except Exception as e:
        st.error(str(e))
        return None
    finally:
        try: os.unlink(out)
        except: pass


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_full_analysis(ticker: str) -> dict:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from agents.fundamental_agent import run_fundamental_agent
    from agents.news_agent import run_news_agent
    from agents.risk_agent import run_risk_agent
    from agents.classifier_agent import run_classifier_agent
    from tools.estimate_revision import apply_estimate_adjustments
    from graph.supervisor import synthesize_memo, _build_quality_checks

    steps = st.status(f"Analyse läuft für **{ticker}**…", expanded=True)
    with steps as status:

        # 0) Classifier
        st.write("🏷️  **Classifier** — Geschäftsmodell-Klassifikation…")
        try:
            bmc = run_classifier_agent(ticker)
            st.write(f"   ✅ {bmc.get('business_model_type')} | "
                     f"Confidence {bmc.get('classification_confidence',0):.2f} | "
                     f"Peers: {', '.join(bmc.get('suggested_peers',[]) or ['-'])}")
        except Exception as e:
            st.write(f"   ⚠ Fallback: {e}"); bmc = None

        # 1) Fundamental
        st.write("🔍  **Fundamental-Agent** — IR-Daten & Bewertung…")
        f_out = run_fundamental_agent(ticker, business_model_context=bmc)
        f_out = f_out if isinstance(f_out,dict) else f_out.model_dump()
        f_conf = float(f_out.get("self_confidence",0.70))
        st.write(f"   ✅ FV: {f_out.get('fair_value_estimate')} | "
                 f"Emp: {f_out.get('recommendation')} | "
                 f"Upside: {f_out.get('upside_downside_pct')}% | Conf: {f_conf:.2f}")

        # 2) News
        st.write("📰  **News/Sentiment-Agent** — Makro & Nachrichten…")
        n_out = run_news_agent(ticker,
                    f"FV:{f_out.get('fair_value_estimate')}, Emp:{f_out.get('recommendation')}",
                    business_model_context=bmc)
        n_out = n_out if isinstance(n_out,dict) else n_out.model_dump()
        n_conf = float(n_out.get("self_confidence",0.70))
        st.write(f"   ✅ Sentiment: {n_out.get('overall_sentiment_score')}/10 | "
                 f"Makro: {n_out.get('overall_macro_direction')} | Conf: {n_conf:.2f}")

        # 2b) Estimate Revision
        rev_est = None
        _adjs = n_out.get("estimate_adjustments",[])
        if _adjs:
            st.write("📐  **Estimate-Revision** — Makro-Adjustments…")
            try:
                rev_est = apply_estimate_adjustments(
                    fundamental_output=f_out,
                    adjustments=_adjs,
                    news_agent_confidence=n_conf,
                )
                st.write(f"   ✅ {len(rev_est['adjustments_applied'])} Adj | "
                         f"Umsatz Δ {rev_est['revenue_delta_pct']:+.1f}% | "
                         f"EPS Δ {rev_est['eps_delta_pct']:+.1f}%")
            except Exception as e:
                st.write(f"   ⚠ {e}"); rev_est = None

        # 2c) Thematic
        th_analysis = None
        try:
            from agents.thematic_agent import run_thematic_agent
            st.write("🌐  **Thematic-Agent** — Megatrends…")
            th_analysis = run_thematic_agent(ticker=ticker,fundamental_output=f_out,
                                             news_output=n_out,business_model_context=bmc)
            if th_analysis:
                st.write(f"   ✅ {len(th_analysis.get('trends',[]))} Trends | "
                         f"{th_analysis.get('net_thematic_assessment','?')}")
        except Exception as e:
            st.write(f"   ⚠ Thematic: {e}")

        # 2d) Optionality
        opt_analysis = None
        _bmc = bmc or {}
        if _bmc.get("business_model_type") == "optionality_play" or _bmc.get("requires_optionality_analysis"):
            try:
                from agents.optionality_agent import run_optionality_agent
                st.write("🎲  **Optionality-Agent** — Real Options…")
                opt_analysis = run_optionality_agent(
                    ticker=ticker,fundamental_output=f_out,thematic_context=th_analysis,
                    news_output=n_out,business_model_context=_bmc)
                if opt_analysis:
                    st.write(f"   ✅ FV: {opt_analysis.get('probability_weighted_value')} | "
                             f"Runway: {opt_analysis.get('runway_months')} Mt")
            except Exception as e:
                st.write(f"   ⚠ Optionality: {e}")

        # 2e) Forward Estimates
        fwd_est = None
        try:
            from agents.forward_estimate_agent import run_forward_estimate_agent
            from tools.finance_tools import get_consensus_estimates
            st.write("📈  **Forward-Estimate-Agent** — Wachstums-Projektion…")
            try: _cons = get_consensus_estimates(ticker)
            except: _cons = None
            fwd_est = run_forward_estimate_agent(
                ticker=ticker,fundamental_output=f_out,news_output=n_out,
                business_model_context=bmc,thematic_context=th_analysis,
                consensus_estimates=_cons)
            if fwd_est:
                st.write(f"   ✅ {fwd_est.get('overall_thesis','')[:80]}")
        except Exception as e:
            st.write(f"   ⚠ Forward-Estimates: {e}")

        # 3) Risk
        st.write("⚖️  **Risk-Agent** — Advocatus Diaboli…")
        r_out = run_risk_agent(ticker,f_out,n_out,business_model_context=bmc)
        r_out = r_out if isinstance(r_out,dict) else r_out.model_dump()
        r_conf = float(r_out.get("self_confidence",0.70))
        st.write(f"   ✅ Gegenposition zu {r_out.get('original_recommendation')} | Conf: {r_conf:.2f}")

        # 4) Quality
        st.write("🔎  **Qualitätsprüfung**…")
        qc = _build_quality_checks(f_out,n_out,r_out)
        ok  = sum(1 for c in qc if c["result"]=="bestanden")
        wrn = sum(1 for c in qc if c["result"]=="Warnung")
        err = sum(1 for c in qc if c["result"]=="fehlgeschlagen")
        st.write(f"   ✅ {ok} bestanden · ⚠️ {wrn} Warnungen · ❌ {err} Fehler")

        # 5) Supervisor
        st.write("✍️  **Supervisor** — Synthese…")
        conf_scores = {"fundamental":f_conf,"news":n_conf,"risk":r_conf}
        result = synthesize_memo(
            ticker,f_out,n_out,r_out,
            quality_checks=qc,
            business_model_classification=bmc,
            agent_confidence_scores=conf_scores,
            revised_estimates=rev_est,
            forward_estimates=fwd_est,
            thematic_analysis=th_analysis,
            optionality_analysis=opt_analysis,
        )
        result = result if isinstance(result,dict) else result.model_dump()
        # market_cap fallback
        if not result.get("market_cap"):
            mc_bn = f_out.get("market_cap_bn")
            if mc_bn:
                ccy_s = f_out.get("currency","")
                result["market_cap"] = f"{float(mc_bn):.1f} Mrd. {ccy_s}".strip()

        st.write(f"   ✅ Empfehlung: **{result.get('final_recommendation')}** | "
                 f"PT: {result.get('price_target')} | Conviction: {result.get('conviction_level')}")
        status.update(label=f"✅ Fertig — {result.get('company',ticker)}", state="complete", expanded=False)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INIT
# ══════════════════════════════════════════════════════════════════════════════

for key, default in {
    "authenticated": False,
    "username": "",
    "page": "home",
    "result": None,
    "ticker": None,
    "search_results": [],
    "last_query": "",
    "selected_ticker": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

def page_login():
    st.markdown("""
    <div class="login-wrap">
      <div class="login-card">
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="login-logo">
      <div class="login-logo-text">KI-Co<span>·</span>Analyst</div>
      <div class="login-subtitle">Equity Research Platform · BFH 2025/26</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    username = st.text_input("Benutzername", placeholder="admin", key="login_user")
    password = st.text_input("Passwort", type="password", placeholder="••••••••", key="login_pw")
    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("Anmelden →", type="primary", use_container_width=True):
        if _verify(username.strip(), password):
            st.session_state.authenticated = True
            st.session_state.username = username.strip()
            st.rerun()
        else:
            st.error("Ungültige Anmeldedaten.")

    st.markdown("""
    <div style="text-align:center; margin-top:1.5rem; font-size:0.78rem; color:#8a9bb0;">
      Demo-Zugang: admin / analyst2025
    </div>
    """, unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TOPBAR
# ══════════════════════════════════════════════════════════════════════════════

def render_topbar():
    now = datetime.now().strftime("%d.%m.%Y  %H:%M")
    st.markdown(f"""
    <div class="topbar">
      <div class="topbar-brand">KI-Co<span>·</span>Analyst</div>
      <div class="topbar-meta">{now} · {st.session_state.username}</div>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.markdown(f"""
        <div style="padding:1.5rem 0 1rem 0; text-align:center;">
          <div style="font-family:'Playfair Display',serif; font-size:1.4rem;
                      font-weight:700; color:white;">
            KI-Co<span style="color:{GOLD};">·</span>Analyst
          </div>
          <div style="font-size:0.72rem; color:{GRAY}; margin-top:4px;
                      text-transform:uppercase; letter-spacing:0.08em;">
            Research Platform
          </div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        nav_items = [
            ("home",     "🏠", "Dashboard"),
            ("analyse",  "🔍", "Analyse"),
            ("history",  "📂", "Historie"),
            ("settings", "⚙️", "Einstellungen"),
        ]
        for page_id, icon, label in nav_items:
            active = "active" if st.session_state.page == page_id else ""
            if st.button(f"{icon}  {label}", key=f"nav_{page_id}",
                         use_container_width=True):
                st.session_state.page = page_id
                st.rerun()

        st.divider()

        # Quick Analyse Input (always visible)
        st.markdown(f"<div style='font-size:0.8rem;color:{GRAY};margin-bottom:6px;'>Schnellsuche</div>",
                    unsafe_allow_html=True)
        company_query = st.text_input("Aktie suchen", placeholder="Holcim, Apple…",
                                      label_visibility="collapsed", key="nav_search")
        if len(company_query) >= 2 and company_query != st.session_state.last_query:
            with st.spinner(""):
                st.session_state.search_results = search_ticker(company_query)
                st.session_state.last_query = company_query

        if st.session_state.search_results:
            opts = [r["display"] for r in st.session_state.search_results]
            opts_map = {r["display"]: r["ticker"] for r in st.session_state.search_results}
            sel = st.radio("", opts, label_visibility="collapsed", key="nav_radio")
            if sel:
                st.session_state.selected_ticker = opts_map[sel]
                st.markdown(f"<div style='font-size:0.8rem;color:{GOLD};'>✓ {opts_map[sel]}</div>",
                            unsafe_allow_html=True)
        elif len(company_query) >= 2:
            manual = st.text_input("Ticker direkt", placeholder="HOLN.SW",
                                   label_visibility="collapsed", key="nav_manual")
            if manual:
                st.session_state.selected_ticker = manual.upper().strip()

        if st.session_state.selected_ticker:
            if st.button("▶  Analyse starten", type="primary",
                         use_container_width=True, key="nav_run"):
                st.session_state.page = "analyse"
                st.session_state["_trigger_run"] = True
                st.rerun()

        st.divider()
        # Beispiel-Ticker
        st.markdown(f"<div style='font-size:0.75rem;color:{GRAY};margin-bottom:6px;'>Beispiele</div>",
                    unsafe_allow_html=True)
        cols = st.columns(2)
        examples = [("Holcim","HOLN.SW"),("Nestlé","NESN.SW"),("Apple","AAPL"),
                    ("Microsoft","MSFT"),("Novartis","NOVN.SW"),("Rigetti","RGTI")]
        for i,(name,t) in enumerate(examples):
            with cols[i%2]:
                if st.button(name, key=f"ex_{t}", use_container_width=True):
                    st.session_state.selected_ticker = t
                    st.session_state.page = "analyse"
                    st.session_state["_trigger_run"] = True
                    st.rerun()

        st.divider()
        if st.button("🚪  Abmelden", use_container_width=True, key="logout"):
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD (HOME)
# ══════════════════════════════════════════════════════════════════════════════

def page_home():
    history = load_history()

    # Hero
    st.markdown(f"""
    <div class="hero">
      <div class="hero-eyebrow">KI-gestützte Aktienanalyse · BFH Bachelor Thesis</div>
      <div class="hero-title">Institutional-Grade<br>Equity Research — automatisiert.</div>
      <div class="hero-subtitle">
        Sieben spezialisierte KI-Agenten analysieren Fundamentaldaten, IR-Dokumente,
        Makro-Indikatoren und Risiken — und synthetisieren ein vollständiges
        Investment Memo in 60–90 Sekunden.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Stat-Kacheln
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div class="card card-accent">
          <div class="card-title">Analysen gesamt</div>
          <div class="card-value">{len(history)}</div>
          <div class="card-sub">seit Inbetrieb­nahme</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        last = history[0] if history else {}
        st.markdown(f"""<div class="card card-accent">
          <div class="card-title">Letzte Analyse</div>
          <div class="card-value" style="font-size:1.3rem;">{last.get('ticker','-')}</div>
          <div class="card-sub">{last.get('date','-')}</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="card card-accent">
          <div class="card-title">KI-Agenten</div>
          <div class="card-value">7</div>
          <div class="card-sub">Classifier + 6 Spezialisten</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="card card-accent">
          <div class="card-title">Modelle</div>
          <div class="card-value" style="font-size:1.1rem;">Claude + GPT</div>
          <div class="card-sub">Sonnet 4.6 + GPT-4o</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([2,1])

    with left:
        st.markdown('<div class="section-head">Letzte Analysen</div>', unsafe_allow_html=True)
        if not history:
            st.info("Noch keine Analysen — starten Sie mit der Suche in der Sidebar.")
        for d in history[:6]:
            rec   = d.get("final_recommendation","HALTEN")
            rec_b = badge_rec(rec)
            pt    = d.get("price_target","-")
            usd   = d.get("upside_downside_pct",0)
            ccy   = d.get("currency","")
            up_h  = upside_html(usd)
            st.markdown(f"""
            <div class="hist-card">
              <div>
                <div class="hist-ticker">{d.get('ticker','-')}</div>
                <div class="hist-company">{d.get('company','-')}</div>
              </div>
              <div style="display:flex;align-items:center;gap:1rem;">
                {rec_b}
                <div style="text-align:right;">
                  <div style="font-size:0.85rem;font-weight:600;color:{NAVY};">
                    {ccy} {safe_num(pt)} PT
                  </div>
                  <div style="font-size:0.82rem;">{up_h}</div>
                </div>
              </div>
              <div class="hist-date">{d.get('date','-')}</div>
            </div>""", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="section-head">Agenten-Pipeline</div>', unsafe_allow_html=True)
        agents = [
            ("🏷️","Classifier","Geschäftsmodell-Klassifikation"),
            ("🔍","Fundamental","IR-Dokumente · DCF · Multiples"),
            ("📰","News/Sentiment","Makro · Branche · Nachrichten"),
            ("📐","Estimate Revision","Makro-adjustierte Schätzungen"),
            ("🌐","Thematic","Megatrends · Adoptionskurven"),
            ("🎲","Optionality","Real Options (Pre-Revenue)"),
            ("📈","Forward Estimates","Wachstums-Projektion"),
            ("⚖️","Risk / Advocatus","Gegenposition · Szenarien"),
            ("✍️","Supervisor","Synthese · Qualitätsprüfung"),
        ]
        for icon,name,desc in agents:
            st.markdown(f"""
            <div style="display:flex;gap:0.75rem;padding:0.55rem 0;
                        border-bottom:1px solid {GRAY_L};">
              <span style="font-size:1.1rem;width:1.5rem;flex-shrink:0;">{icon}</span>
              <div>
                <div style="font-size:0.88rem;font-weight:600;color:{NAVY};">{name}</div>
                <div style="font-size:0.78rem;color:{GRAY};">{desc}</div>
              </div>
            </div>""", unsafe_allow_html=True)

    _footer()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ANALYSE
# ══════════════════════════════════════════════════════════════════════════════

def page_analyse():
    node_ready,_ = ensure_node_deps()

    # Auto-run when triggered from sidebar
    ticker = st.session_state.get("selected_ticker","").upper().strip()
    if st.session_state.pop("_trigger_run", False) and ticker:
        try:
            result = run_full_analysis(ticker)
            result["ticker"] = ticker
            st.session_state.result = result
            st.session_state.ticker = ticker
            save_to_history(result)
            st.rerun()
        except Exception as e:
            st.error(f"Fehler: {e}")

    # If no result yet
    if not st.session_state.result:
        st.markdown(f"""
        <div style="text-align:center;padding:5rem 2rem;color:{GRAY};">
          <div style="font-size:3.5rem;margin-bottom:1.2rem;opacity:0.5;">📊</div>
          <div style="font-family:'Playfair Display',serif;font-size:1.6rem;
                      color:{NAVY};margin-bottom:0.5rem;">Bereit zur Analyse</div>
          <div style="font-size:0.95rem;max-width:380px;margin:0 auto;line-height:1.8;">
            Suchen Sie eine Aktie in der linken Sidebar und klicken Sie
            <strong>Analyse starten</strong>.
          </div>
        </div>""", unsafe_allow_html=True)
        return

    data  = st.session_state.result
    rec   = data.get("final_recommendation","HALTEN")
    conv  = data.get("conviction_level","-")
    pt    = data.get("price_target",0)
    price = data.get("current_price",0)
    updn  = data.get("upside_downside_pct",0)
    ccy   = data.get("currency","")
    company = data.get("company","")
    tkr   = data.get("ticker","")
    date  = data.get("date",datetime.now().strftime("%Y-%m-%d"))
    score = data.get("data_consistency_score",0)
    mktcap= data.get("market_cap","n/v")

    # ── Hero strip ──
    star = {"hoch":"★★★","mittel":"★★☆","niedrig":"★☆☆"}.get(conv,"★☆☆")
    score_col = GOLD if score >= 7 else ("#cc6b2e" if score >= 5 else RED)
    st.markdown(f"""
    <div style="background:{WHITE};border:1px solid {GRAY_L};border-radius:14px;
                padding:1.5rem 2rem;margin-bottom:1.2rem;
                box-shadow:0 2px 12px rgba(0,0,0,0.05);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem;">
        <div>
          <div style="font-family:'Playfair Display',serif;font-size:1.9rem;
                      font-weight:700;color:{NAVY};">{company}</div>
          <div style="color:{GRAY};font-size:0.88rem;margin-top:3px;">
            {tkr} · {data.get('sector','')} · {date}
          </div>
          <div style="margin-top:0.8rem;display:flex;align-items:center;gap:0.75rem;">
            {badge_rec(rec)}
            <span style="color:{GRAY};font-size:0.88rem;">
              Conviction: <strong>{conv}</strong> {star}
            </span>
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.72rem;color:{GRAY};text-transform:uppercase;
                      letter-spacing:0.06em;margin-bottom:2px;">Konsistenz-Score</div>
          <div style="font-family:'Playfair Display',serif;font-size:2.8rem;
                      font-weight:700;color:{score_col};line-height:1;">
            {score}<span style="font-size:1rem;color:{GRAY};">/10</span>
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 5 KPI-Kacheln ──
    m1,m2,m3,m4,m5 = st.columns(5)
    def kpi(col, label, value, sub=""):
        with col:
            st.markdown(f"""<div class="card" style="text-align:center;">
              <div class="card-title">{label}</div>
              <div style="font-family:'Playfair Display',serif;font-size:1.5rem;
                          font-weight:700;color:{NAVY};">{value}</div>
              {f'<div class="card-sub">{sub}</div>' if sub else ''}
            </div>""", unsafe_allow_html=True)

    kpi(m1,"Aktueller Kurs",f"{ccy} {safe_num(price)}")
    kpi(m2,"Price Target (12M)",f"{ccy} {safe_num(pt)}")
    kpi(m3,"Upside/Downside",upside_html(updn))
    kpi(m4,"Marktkapitalisierung",mktcap)
    kpi(m5,"Datum",date)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Executive Summary ──
    botline = data.get("summary_bottom_line","")
    execsum = data.get("executive_summary","")
    if botline or execsum:
        rc = {
            "KAUFEN":GREEN,"ÜBERGEWICHTEN":"#2e9e5b",
            "HALTEN":AMBER,"UNTERGEWICHTEN":"#cc6b2e","VERKAUFEN":RED
        }.get(rec.upper(),NAVY)
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#f8fbff,#eef4fb);
                    border-left:4px solid {rc};border-radius:10px;
                    padding:1.3rem 1.5rem;margin-bottom:1.5rem;">
          <div style="font-size:0.7rem;font-weight:700;text-transform:uppercase;
                      letter-spacing:0.08em;color:{GRAY};margin-bottom:0.6rem;">
            Das Wichtigste in Kürze
          </div>
          {'<div style="font-size:1rem;font-weight:700;color:' + rc + ';margin-bottom:0.5rem;">💡 ' + botline + '</div>' if botline else ''}
          {'<div style="font-size:0.92rem;line-height:1.8;color:#2c3e50;">' + execsum + '</div>' if execsum else ''}
        </div>""", unsafe_allow_html=True)

    # ── Tabs ──
    t1,t2,t3,t4,t5 = st.tabs([
        "📋  Investment Memo","📊  Bewertung","📰  Makro & Sentiment",
        "⚠️  Risiken & Szenarien","✅  Qualitätsprüfung"
    ])

    # TAB 1 — MEMO
    with t1:
        col_l,col_r = st.columns([3,2])
        with col_l:
            st.markdown('<div class="section-head">Unternehmensbeschreibung</div>',unsafe_allow_html=True)
            st.markdown(data.get("company_description","-"))

            st.markdown('<div class="section-head">Investment Case</div>',unsafe_allow_html=True)
            for item in data.get("investment_case",[]):
                point  = item.get("point","") if isinstance(item,dict) else str(item)
                source = item.get("source","") if isinstance(item,dict) else ""
                st.markdown(f'<div class="ic-bullet">{point}</div>',unsafe_allow_html=True)
                if source: st.caption(source)

            st.markdown('<div class="section-head">Finale Begründung</div>',unsafe_allow_html=True)
            st.markdown(f"""
            <div style="background:{OFF_W};border-radius:8px;padding:1rem 1.2rem;
                        font-size:0.87rem;line-height:1.75;color:#495057;">
              {data.get('final_reasoning','-')}
            </div>""", unsafe_allow_html=True)

        with col_r:
            st.markdown('<div class="section-head">Makro-Ampel</div>',unsafe_allow_html=True)
            for amp in data.get("macro_ampel",[]):
                icon = ampel_icon(amp.get("signal","neutral"))
                st.markdown(f"""
                <div style="display:flex;gap:0.75rem;padding:0.55rem 0;
                            border-bottom:1px solid {GRAY_L};">
                  <span style="font-size:1.1rem;flex-shrink:0;">{icon}</span>
                  <div>
                    <div style="font-weight:600;font-size:0.85rem;color:{NAVY};">
                      {amp.get('category','')}
                    </div>
                    <div style="font-size:0.8rem;color:{GRAY};margin-top:2px;">
                      {amp.get('key_point','')}
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)

            st.markdown('<div class="section-head">Advocatus Diaboli</div>',unsafe_allow_html=True)
            st.markdown(f"""
            <div style="background:#fff5f5;border:1px solid #fca5a5;border-radius:8px;
                        padding:1rem;font-size:0.84rem;line-height:1.6;color:#7f1d1d;">
              {data.get('advocatus_diaboli_summary','-')}
            </div>""", unsafe_allow_html=True)

            st.markdown('<div class="section-head">Quellen</div>',unsafe_allow_html=True)
            for src in data.get("sources",[]):
                st.markdown(f"<div style='font-size:0.78rem;color:{GRAY};padding:2px 0;'>• {src}</div>",
                            unsafe_allow_html=True)

    # TAB 2 — BEWERTUNG
    with t2:
        vt = data.get("valuation_table",[])
        if vt:
            st.markdown('<div class="section-head">Bewertungs-Multiples</div>',unsafe_allow_html=True)
            rows = []
            for r in vt:
                a = r.get("assessment","FAIR")
                rows.append({
                    "Kennzahl":     r.get("metric",""),
                    "Aktuell":      r.get("current_value","-"),
                    "Peer Ø":       r.get("peer_average","-"),
                    "Hist. Ø":      r.get("historical_average","-"),
                    "Einschätzung": {"ELEVATED":"🔴 ELEVATED","FAIR":"🟢 FAIR","DISCOUNT":"🔵 DISCOUNT"}.get(a,a),
                    "Quelle":       r.get("source",""),
                })
            st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
            fig_v = chart_valuation(vt)
            if fig_v:
                st.plotly_chart(fig_v,use_container_width=True)
                st.caption("📖 Blauer Balken (Aktuell) höher als Peer Ø → Aktie teuer. Tiefer → günstiger.")

        ce = data.get("consensus_estimates",[])
        if ce:
            st.markdown('<div class="section-head">Konsensschätzungen</div>',unsafe_allow_html=True)
            rows_ce = [{"Jahr":("📊 " if r.get("type")=="E" else "")+str(r.get("year","")),
                        "Umsatz":r.get("revenue_bn","-"),
                        "EBITDA-%":r.get("ebitda_margin_pct","-"),
                        "EPS":r.get("eps","-"),
                        "KGV":r.get("pe_ratio","-")} for r in ce]
            st.dataframe(pd.DataFrame(rows_ce),use_container_width=True,hide_index=True)
            fig_m = chart_margin_trend(ce)
            if fig_m:
                st.plotly_chart(fig_m,use_container_width=True)

        ff = data.get("full_financials",[])
        if ff:
            st.markdown('<div class="section-head">Vollständige Finanzübersicht (6 Jahre)</div>',unsafe_allow_html=True)
            rows_ff = [{"Jahr":("📊 " if y.get("type")=="E" else "")+str(y.get("year","")),
                        "Umsatz":y.get("revenue_bn","n/v"),"EBITDA":y.get("ebitda_bn","n/v"),
                        "EBITDA-%":y.get("ebitda_margin_pct","-"),"EBIT-%":y.get("ebit_margin_pct","n/v"),
                        "EPS":y.get("eps_adj","n/v"),"DPS":y.get("dps","n/v"),
                        "FCF":y.get("fcf_bn","n/v"),"ND/EBITDA":y.get("nd_ebitda","n/v"),
                        "ROIC":y.get("roic_pct","n/v"),"Quelle":y.get("source","")} for y in ff]
            st.dataframe(pd.DataFrame(rows_ff),use_container_width=True,hide_index=True)

        pc = data.get("peer_comparison") or {}
        peers = pc.get("peers",[])
        if peers:
            st.markdown('<div class="section-head">Peer-Vergleich</div>',unsafe_allow_html=True)
            avg_p = pc.get("sector_averages",{})
            sub_p = pc.get("subject_company",{})
            rows_p = []
            for p in [*peers, avg_p, sub_p]:
                if not p: continue
                is_sub = p.get("ticker") == tkr
                is_avg = p.get("ticker") == "AVG"
                def _norm_div(v):
                    try: f=float(v); return round(f/100,2) if f>20 else round(f,2)
                    except: return v
                rows_p.append({"Unternehmen":("⭐ " if is_sub else "Ø " if is_avg else "")+str(p.get("company","")),
                               "Land":p.get("country",""),
                               "EV/EBITDA":p.get("ev_ebitda","-"),"Fwd P/E":p.get("forward_pe","-"),
                               "EBIT-%":p.get("ebit_margin_pct","-"),"ND/EBITDA":p.get("nd_ebitda","-"),
                               "Div %":_norm_div(p.get("dividend_yield_pct","-")),
                               "Rev-Wachstum":p.get("revenue_growth_pct","-")})
            st.dataframe(pd.DataFrame(rows_p),use_container_width=True,hide_index=True)

    # TAB 3 — MAKRO
    with t3:
        cl,cr = st.columns(2)
        with cl:
            st.markdown('<div class="section-head">Makro-Ampel</div>',unsafe_allow_html=True)
            for amp in data.get("macro_ampel",[]):
                sig = amp.get("signal","neutral")
                icon = ampel_icon(sig)
                bg = {"positiv":"#f0fdf4","negativ":"#fff5f5"}.get(sig,"#fffbeb")
                bd = {"positiv":"#86efac","negativ":"#fca5a5"}.get(sig,"#fcd34d")
                st.markdown(f"""
                <div style="background:{bg};border:1px solid {bd};border-radius:8px;
                            padding:0.8rem 1rem;margin-bottom:0.5rem;">
                  <div style="font-weight:600;font-size:0.88rem;">
                    {icon} {amp.get('category','')}
                    <span style="float:right;font-size:0.75rem;color:{GRAY};">{sig.upper()}</span>
                  </div>
                  <div style="font-size:0.82rem;color:#495057;margin-top:4px;line-height:1.5;">
                    {amp.get('key_point','')}
                  </div>
                </div>""", unsafe_allow_html=True)

        with cr:
            st.markdown('<div class="section-head">Monitoring-Checkliste</div>',unsafe_allow_html=True)
            for item in data.get("monitoring_checklist",[]):
                st.markdown(f"""
                <div style="display:flex;gap:0.6rem;padding:0.45rem 0;
                            border-bottom:1px solid {GRAY_L};font-size:0.84rem;color:#495057;">
                  <span style="color:{GOLD};flex-shrink:0;">□</span>{item}
                </div>""", unsafe_allow_html=True)

    # TAB 4 — RISIKEN
    with t4:
        opt = data.get("optionality_analysis")
        if opt and isinstance(opt,dict):
            st.markdown('<div class="section-head">🎲 Optionality-Bewertung</div>',unsafe_allow_html=True)
            oc1,oc2,oc3 = st.columns(3)
            st.metric("Cash-Runway",f"{opt.get('runway_months','n/v')} Mt",label_visibility="visible")
            with oc1: st.metric("Cash-Runway",f"{opt.get('runway_months','n/v')} Mt")
            with oc2: st.metric("Fairer Wert",f"{ccy} {opt.get('probability_weighted_value','n/v')}")
            with oc3: st.metric("Verwässerungsrisiko",opt.get('dilution_risk','?').upper())
            if opt.get("binary_risk_warning"): st.warning(opt["binary_risk_warning"])

        sc_list = data.get("scenarios",[])
        if sc_list:
            st.markdown('<div class="section-head">Szenarien</div>',unsafe_allow_html=True)
            fig_s = chart_scenarios(sc_list,ccy,_parse_num(price))
            if fig_s:
                st.plotly_chart(fig_s,use_container_width=True)
                st.caption("Balken = Kursziel je Szenario. Prozentzahl = Eintrittswahrscheinlichkeit.")
            sc_cols = st.columns(len(sc_list))
            css_m = {"Bear Case":"sc-bear","Base Case":"sc-base","Bull Case":"sc-bull"}
            icon_m = {"Bear Case":"🐻","Base Case":"⚖️","Bull Case":"🐂"}
            for col,sc in zip(sc_cols,sc_list):
                nm = sc.get("name","")
                with col:
                    st.markdown(f"""
                    <div class="{css_m.get(nm,'sc-base')}">
                      <div style="font-weight:700;font-size:0.95rem;margin-bottom:0.5rem;">
                        {icon_m.get(nm,'')} {nm}
                      </div>
                      <div style="font-family:'Playfair Display',serif;font-size:1.5rem;
                                  font-weight:700;margin-bottom:0.3rem;">
                        {ccy} {safe_num(sc.get('price_target',0))}
                      </div>
                      <div style="font-size:0.8rem;color:{GRAY};margin-bottom:0.8rem;">
                        P = <strong>{sc.get('probability_pct',0)}%</strong>
                      </div>
                      <div style="font-size:0.81rem;line-height:1.5;">
                        <strong>Kernannahme:</strong><br>{sc.get('key_assumption','')}
                      </div>
                      <div style="font-size:0.78rem;color:{GRAY};margin-top:0.5rem;">
                        Trigger: {sc.get('trigger','')}
                      </div>
                    </div>""", unsafe_allow_html=True)

        st.markdown('<div class="section-head">Quantifizierte Risiken</div>',unsafe_allow_html=True)
        for risk in data.get("key_risks",[]):
            st.markdown(f"""
            <div style="background:#fff5f5;border-left:3px solid #f87171;
                        padding:0.6rem 1rem;margin-bottom:0.4rem;border-radius:0 6px 6px 0;
                        font-size:0.87rem;line-height:1.5;">⚠️ {risk}</div>""",unsafe_allow_html=True)

        st.markdown('<div class="section-head">Conviction Killers</div>',unsafe_allow_html=True)
        for ck in data.get("conviction_killers",[]):
            desc = ck.get("description","") if isinstance(ck,dict) else str(ck)
            mon  = ck.get("monitoring_indicator","") if isinstance(ck,dict) else ""
            st.markdown(f"""
            <div class="ck-box">
              <div style="font-weight:600;font-size:0.88rem;color:#7f1d1d;">🚨 {desc}</div>
              {f'<div style="font-size:0.8rem;color:#991b1b;margin-top:4px;">→ Monitor: {mon}</div>' if mon else ''}
            </div>""", unsafe_allow_html=True)

    # TAB 5 — QUALITÄT
    with t5:
        ql,qr = st.columns([2,1])
        with ql:
            st.markdown('<div class="section-head">Qualitätschecks</div>',unsafe_allow_html=True)
            for c in data.get("quality_checks",[]):
                rv = c.get("result","")
                icon = {"bestanden":"✅","Warnung":"⚠️","fehlgeschlagen":"❌"}.get(rv,"ℹ️")
                bg   = {"bestanden":"#f0fdf4","Warnung":"#fffbeb","fehlgeschlagen":"#fff5f5"}.get(rv,OFF_W)
                st.markdown(f"""
                <div style="background:{bg};border-radius:6px;padding:0.65rem 1rem;
                            margin-bottom:0.35rem;font-size:0.84rem;">
                  <span style="margin-right:0.4rem;">{icon}</span>
                  <strong>{c.get('check','')}</strong>
                  <div style="color:{GRAY};margin-top:2px;font-size:0.78rem;">{c.get('comment','')}</div>
                </div>""", unsafe_allow_html=True)

        with qr:
            st.markdown('<div class="section-head">Score</div>',unsafe_allow_html=True)
            sc2 = data.get("data_consistency_score",0)
            sc_c = GREEN if sc2>=7 else (AMBER if sc2>=5 else RED)
            st.markdown(f"""
            <div style="text-align:center;padding:2rem 1rem;">
              <div style="font-family:'Playfair Display',serif;font-size:4.5rem;
                          font-weight:700;color:{sc_c};line-height:1;">
                {sc2}
              </div>
              <div style="color:{GRAY};font-size:0.88rem;">von 10 Punkten</div>
              <div style="margin-top:1rem;font-size:0.82rem;color:#495057;line-height:1.6;">
                {data.get('consistency_notes','')}
              </div>
            </div>""", unsafe_allow_html=True)

    # ── Downloads ──
    st.divider()
    st.markdown(f"<div style='font-size:1rem;font-weight:600;color:{NAVY};margin-bottom:0.8rem;'>📥 Memo herunterladen</div>",
                unsafe_allow_html=True)
    d1,d2,d3 = st.columns(3)

    with d1:
        if st.button("📄  Word (.docx)",type="primary",use_container_width=True,
                     disabled=not node_ready,key="dl_word_btn"):
            with st.spinner("Erstelle Word-Dokument…"):
                buf = generate_word_memo(data)
                if buf:
                    st.download_button("💾  Herunterladen",data=buf,
                        file_name=f"KI-Co-Analyst_{tkr}_{datetime.now().strftime('%Y%m%d')}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True,key="dl_word_dl")
                    st.success("✅ Word-Memo bereit")
    with d2:
        json_str = json.dumps(data,indent=2,ensure_ascii=False,default=str)
        st.download_button("📋  JSON",data=json_str,
            file_name=f"KI-Co-Analyst_{tkr}_data.json",mime="application/json",
            use_container_width=True,key="dl_json")
    with d3:
        try:
            from graph.supervisor import format_investment_memo
            txt_memo = format_investment_memo(data)
        except Exception:
            txt_memo = json_str
        st.download_button("📝  Text (.txt)",data=txt_memo,
            file_name=f"KI-Co-Analyst_{tkr}_memo.txt",mime="text/plain",
            use_container_width=True,key="dl_txt")

    _footer()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: HISTOIRE
# ══════════════════════════════════════════════════════════════════════════════

def page_history():
    st.markdown(f'<div style="font-family:\'Playfair Display\',serif;font-size:1.6rem;font-weight:700;color:{NAVY};margin-bottom:1.5rem;">Analyse-Historie</div>',
                unsafe_allow_html=True)
    history = load_history()
    if not history:
        st.info("Noch keine gespeicherten Analysen.")
        return

    search = st.text_input("Suche in Analysen", placeholder="Ticker oder Firmenname…",
                           key="hist_search")
    filtered = [d for d in history if
                not search or search.lower() in d.get("ticker","").lower()
                or search.lower() in d.get("company","").lower()]

    for d in filtered:
        rec   = d.get("final_recommendation","HALTEN")
        usd   = d.get("upside_downside_pct",0)
        pt    = d.get("price_target","-")
        ccy_h = d.get("currency","")
        with st.expander(
            f"**{d.get('ticker','-')}**  ·  {d.get('company','-')}  ·  {d.get('date','-')}  ·  {rec}"
        ):
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Empfehlung",rec)
            c2.metric("Kursziel",f"{ccy_h} {safe_num(pt)}")
            c3.metric("Upside",f"{safe_num(usd)}%")
            c4.metric("Score",f"{d.get('data_consistency_score','-')}/10")

            botline = d.get("summary_bottom_line","")
            if botline:
                st.markdown(f"> 💡 {botline}")

            st.markdown(f"**Finale Begründung:**\n\n{d.get('final_reasoning','-')}")

            # Re-Laden Button
            if st.button("Diese Analyse anzeigen →", key=f"load_{d.get('_file','')}"):
                st.session_state.result = d
                st.session_state.ticker = d.get("ticker","")
                st.session_state.page = "analyse"
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: EINSTELLUNGEN
# ══════════════════════════════════════════════════════════════════════════════

def page_settings():
    st.markdown(f'<div style="font-family:\'Playfair Display\',serif;font-size:1.6rem;font-weight:700;color:{NAVY};margin-bottom:1.5rem;">Einstellungen</div>',
                unsafe_allow_html=True)

    col_l, col_r = st.columns([1,1])

    with col_l:
        st.markdown('<div class="section-head">Passwort ändern</div>',unsafe_allow_html=True)
        with st.form("pw_form"):
            old_pw = st.text_input("Aktuelles Passwort",type="password")
            new_pw = st.text_input("Neues Passwort",type="password")
            new_pw2= st.text_input("Neues Passwort (wiederholen)",type="password")
            sub = st.form_submit_button("Passwort aktualisieren",type="primary")
        if sub:
            if not _verify(st.session_state.username, old_pw):
                st.error("Aktuelles Passwort falsch.")
            elif new_pw != new_pw2:
                st.error("Passwörter stimmen nicht überein.")
            elif len(new_pw) < 8:
                st.error("Mindestens 8 Zeichen.")
            else:
                creds = _load_credentials()
                creds[st.session_state.username] = _hash(new_pw)
                _save_credentials(creds)
                st.success("✅ Passwort geändert.")

    with col_r:
        st.markdown('<div class="section-head">System-Info</div>',unsafe_allow_html=True)
        node_ready, node_msg = ensure_node_deps()
        st.markdown(f"""
        <div class="card" style="font-size:0.87rem;line-height:2;">
          <div><strong>Angemeldeter Nutzer:</strong> {st.session_state.username}</div>
          <div><strong>Node.js Export:</strong> {'✅ OK' if node_ready else '❌ ' + node_msg}</div>
          <div><strong>Analyse-Modell:</strong> Claude Sonnet 4.6</div>
          <div><strong>Classifier/Tools:</strong> GPT (gpt-5.4-mini)</div>
          <div><strong>Analysen in History:</strong> {len(load_history())}</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="section-head">Peer-Cache leeren</div>',unsafe_allow_html=True)
        if st.button("🗑️  Alle Peer-Caches löschen",use_container_width=True,key="clear_cache"):
            removed = 0
            for fp in Path("ir_cache").rglob("peers.json"):
                try: fp.unlink(); removed += 1
                except: pass
            st.success(f"✅ {removed} Cache-Dateien gelöscht.")

    _footer()


# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════

def _footer():
    st.markdown(f"""
    <div class="footer">
      KI-Co-Analyst · Berner Fachhochschule · Bachelor Thesis 2025/26 · Luca Lüdi
      <br>Kein Ersatz für professionelle Anlageberatung (Art. 3 lit. c FIDLEG)
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ══════════════════════════════════════════════════════════════════════════════

if not st.session_state.authenticated:
    page_login()
else:
    render_topbar()
    render_sidebar()

    page = st.session_state.page
    if page == "home":
        page_home()
    elif page == "analyse":
        page_analyse()
    elif page == "history":
        page_history()
    elif page == "settings":
        page_settings()
    else:
        page_home()
