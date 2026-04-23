"""Unified dark theme for every tradelab HTML artifact.

Single palette matching the AlgoTrade Command Center (the dashboard
served by ``C:\\TradingScripts\\Launch_Dashboard.bat``). No light mode,
no toggle — one consistent trading-terminal look across every report.

Exports:
  * THEME_CSS              — the full stylesheet as a string
  * apply_plotly_theme(fig) — mutate a Plotly figure to use the dark template
"""
from __future__ import annotations


# -------- single-theme CSS matching the Command Center palette ------------

THEME_CSS = r"""
:root {
  /* Surfaces (darkest to lightest) */
  --bg:          #0f1117;
  --bg-input:    #181a20;
  --bg-header:   #181a20;
  --bg-panel:    #1e2028;
  --bg-hover:    #262836;

  /* Borders */
  --border:      #2a2d38;
  --border-soft: #1f2230;

  /* Typography */
  --fg:        #f0f2f5;
  --fg-muted:  #a0a4b0;
  --fg-dim:    #6b7080;

  /* Accent (green = primary, matches CC tabs/buttons) */
  --accent:      #22c55e;
  --accent-soft: rgba(34, 197, 94, 0.08);

  /* Semantic colors */
  --win:   #22c55e;
  --loss:  #ef4444;
  --warn:  #eab308;
  --info:  #3b82f6;
  --violet:#a78bfa;
  --cyan:  #22d3ee;

  /* Verdict pills */
  --v-robust-bg:       rgba(34, 197, 94, 0.12);
  --v-robust-fg:       #22c55e;
  --v-marginal-bg:     rgba(234, 179, 8, 0.12);
  --v-marginal-fg:     #eab308;
  --v-fragile-bg:      rgba(239, 68, 68, 0.12);
  --v-fragile-fg:      #ef4444;
  --v-inconclusive-bg: #262836;
  --v-inconclusive-fg: #a0a4b0;
  --v-unknown-bg:      #1e2028;
  --v-unknown-fg:      #6b7080;

  /* Status chips */
  --s-ported:     #22c55e;
  --s-registered: #3b82f6;
  --s-scaffold:   #eab308;
  --s-archived:   #ef4444;
  --s-canary:     #a0a4b0;
  --s-pending:    #6b7080;

  /* Alerts */
  --alert-bg:     rgba(234, 179, 8, 0.08);
  --alert-border: rgba(234, 179, 8, 0.25);
  --alert-fg:     #eab308;

  --radius: 10px;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI",
               Roboto, Helvetica, Arial, sans-serif;
  color: var(--fg);
  background: var(--bg);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; opacity: 0.9; }
code {
  background: var(--bg-input); padding: 2px 6px;
  border-radius: 3px; font-size: 11px;
  font-family: "SF Mono", Consolas, Menlo, monospace;
  color: var(--fg);
}

/* -------- verdict pills (universal) -------- */
.v-pill {
  display: inline-block; padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.3px; text-transform: uppercase;
}
.v-robust       { background: var(--v-robust-bg);       color: var(--v-robust-fg);
                  border: 1px solid rgba(34, 197, 94, 0.25); }
.v-marginal     { background: var(--v-marginal-bg);     color: var(--v-marginal-fg);
                  border: 1px solid rgba(234, 179, 8, 0.25); }
.v-fragile      { background: var(--v-fragile-bg);      color: var(--v-fragile-fg);
                  border: 1px solid rgba(239, 68, 68, 0.25); }
.v-inconclusive { background: var(--v-inconclusive-bg); color: var(--v-inconclusive-fg); }
.v-unknown      { background: var(--v-unknown-bg);      color: var(--v-unknown-fg); }
.v-why          { font-size: 10px; opacity: 0.7; cursor: help; }

/* -------- status chips (strategy state) -------- */
.status, .chip {
  display: inline-block; padding: 3px 10px;
  border-radius: 8px;
  font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.3px;
}
.s-ported     { background: rgba(34, 197, 94, 0.1); color: var(--s-ported);
                border: 1px solid rgba(34, 197, 94, 0.25); }
.s-registered { background: rgba(59, 130, 246, 0.1); color: var(--s-registered);
                border: 1px solid rgba(59, 130, 246, 0.25); }
.s-scaffold   { background: rgba(234, 179, 8, 0.1); color: var(--s-scaffold);
                border: 1px solid rgba(234, 179, 8, 0.25); }
.s-archived   { background: rgba(239, 68, 68, 0.1); color: var(--s-archived);
                border: 1px solid rgba(239, 68, 68, 0.25); }
.s-canary     { background: var(--bg-header); color: var(--s-canary);
                border: 1px solid var(--border); }
.s-pending    { background: var(--bg-panel); color: var(--s-pending); }

/* -------- KPI cards -------- */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px; margin: 12px 0;
}
.kpi {
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px;
}
.kpi .label, .kpi-label {
  font-size: 11px; color: var(--fg-dim);
  text-transform: uppercase; letter-spacing: 0.5px;
  font-weight: 600; margin-bottom: 6px;
}
.kpi .value, .kpi-value {
  font-size: 22px; font-weight: 700;
  color: var(--fg);
  font-variant-numeric: tabular-nums;
}
.kpi-value.positive { color: var(--win); }
.kpi-value.negative { color: var(--loss); }

/* -------- tables -------- */
table {
  border-collapse: collapse; width: 100%;
  font-size: 13px; color: var(--fg);
}
thead th {
  background: var(--bg-header); padding: 10px 12px;
  text-align: left; font-weight: 600; font-size: 12px;
  color: var(--fg-muted); letter-spacing: 0.3px;
  border-bottom: 1px solid var(--border);
  user-select: none;
}
thead th.num, tbody td.num {
  text-align: right; font-variant-numeric: tabular-nums;
}
tbody td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border-soft);
  vertical-align: middle;
}
tbody tr:hover { background: var(--bg-hover); }
td.strategy { font-weight: 600; }
td.when { color: var(--fg-muted); font-size: 12px; white-space: nowrap; }

/* -------- charts -------- */
.chart {
  background: var(--bg-panel); border: 1px solid var(--border);
  padding: 15px; border-radius: var(--radius); margin-bottom: 12px;
}

/* -------- notes / alerts -------- */
.note {
  background: var(--alert-bg); padding: 12px 16px;
  border: 1px solid var(--alert-border);
  border-radius: var(--radius);
  color: var(--alert-fg); font-size: 13px;
  margin: 15px 0; font-weight: 500;
}
.tl-alert {
  margin: 12px 28px 0; padding: 12px 16px;
  background: var(--alert-bg); border: 1px solid var(--alert-border);
  border-radius: var(--radius); color: var(--alert-fg); font-size: 13px;
  font-weight: 500;
}

/* -------- sparklines + mini-badges -------- */
.tl-spark { display: block; }
.tl-equity-cell { display: flex; align-items: center; gap: 8px; }
.tl-duration {
  font-size: 10px; color: var(--fg-muted);
  background: var(--bg-input);
  padding: 2px 8px; border-radius: 10px;
  white-space: nowrap; border: 1px solid var(--border);
  letter-spacing: 0.3px; font-weight: 500;
}

/* -------- form controls -------- */
input, select, button {
  font-family: inherit; font-size: 13px;
  color: var(--fg); background: var(--bg-input);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 7px 12px;
}
input:focus, select:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
button { cursor: pointer; transition: background 0.15s, border-color 0.15s; }
button:hover { background: var(--bg-hover); border-color: var(--fg-dim); }

/* -------- text helpers -------- */
.tl-muted, .tl-subtitle { color: var(--fg-muted); }
.tl-dim { color: var(--fg-dim); }
.tl-stale { color: var(--loss); font-size: 10px; }
.win { color: var(--win); }
.loss { color: var(--loss); }

/* -------- layouts -------- */
.section { margin-bottom: 24px; }
.section h2 { font-size: 16px; color: var(--fg); margin-bottom: 10px; font-weight: 600; }
.section h3 { font-size: 14px; color: var(--fg-muted); margin: 16px 0 6px; }
.dual-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .dual-grid { grid-template-columns: 1fr; } }
"""


# -------- Plotly dark template matching the CC palette -------------------

def _plotly_template() -> dict:
    """Plotly layout matching the CC bg (#0f1117) with subtle gridlines
    and a green-forward colorway."""
    return {
        "layout": {
            "paper_bgcolor": "#0f1117",
            "plot_bgcolor": "#0f1117",
            "font": {
                "family": 'Inter, -apple-system, "Segoe UI", Roboto, sans-serif',
                "color": "#f0f2f5",
                "size": 12,
            },
            "title": {"font": {"size": 14, "color": "#f0f2f5"}},
            "xaxis": {
                "gridcolor": "#1e2028",
                "linecolor": "#2a2d38",
                "zerolinecolor": "#2a2d38",
                "tickfont": {"color": "#a0a4b0"},
                "title": {"font": {"color": "#a0a4b0", "size": 11}},
            },
            "yaxis": {
                "gridcolor": "#1e2028",
                "linecolor": "#2a2d38",
                "zerolinecolor": "#2a2d38",
                "tickfont": {"color": "#a0a4b0"},
                "title": {"font": {"color": "#a0a4b0", "size": 11}},
            },
            "legend": {
                "bgcolor": "rgba(30,32,40,0.85)",
                "bordercolor": "#2a2d38",
                "borderwidth": 1,
                "font": {"color": "#f0f2f5", "size": 11},
            },
            "hoverlabel": {
                "bgcolor": "#1e2028",
                "bordercolor": "#2a2d38",
                "font": {"color": "#f0f2f5"},
            },
            "colorway": [
                "#22c55e",   # green (primary/accent)
                "#3b82f6",   # blue
                "#a78bfa",   # purple
                "#eab308",   # amber
                "#ef4444",   # red
                "#22d3ee",   # cyan
                "#f97316",   # orange
                "#f472b6",   # pink
            ],
            "margin": {"l": 50, "r": 20, "t": 50, "b": 45},
        }
    }


_TRADELAB_DARK = _plotly_template()


def apply_plotly_theme(fig) -> None:
    """Mutate a Plotly figure to use the tradelab dark (CC-matched) template.

    Called before ``to_html`` / rendering. Safe to call multiple times;
    never raises — a theming failure should not break report generation.
    """
    try:
        fig.update_layout(**_TRADELAB_DARK["layout"])
    except Exception:
        pass
