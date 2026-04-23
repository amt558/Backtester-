"""HTML skeleton for the per-run dashboard.

Uses ``string.Template`` instead of ``str.format()`` so CSS/JS braces stay
literal (no need to escape every ``{`` and ``}``). Placeholders use
``$name`` syntax; ``builder.py`` passes a dict via ``substitute``.

Shared dark/light theme pulled from ``_theme.py``; Plotly charts are baked
with the dark template at render time.
"""
from string import Template

from ._theme import THEME_CSS


_PAGE_CSS = r"""
/* -------- per-run dashboard layout (supplements theme.css) -------- */
.header {
  padding: 20px 30px; background: var(--bg-header);
  border-bottom: 1px solid var(--border);
}
.header h1 { margin: 0; font-size: 22px; color: var(--fg); }
.header .meta {
  font-size: 13px; color: var(--fg-muted);
  margin-top: 6px; line-height: 1.6;
}
.header .verdict {
  display: inline-block; padding: 4px 12px; border-radius: 4px;
  font-weight: 700; font-size: 13px; margin-right: 8px; letter-spacing: 0.3px;
}
.header .verdict.ROBUST       { background: var(--v-robust-bg);       color: var(--v-robust-fg); }
.header .verdict.MARGINAL     { background: var(--v-marginal-bg);     color: var(--v-marginal-fg); }
.header .verdict.INCONCLUSIVE { background: var(--v-inconclusive-bg); color: var(--v-inconclusive-fg); }
.header .verdict.FRAGILE      { background: var(--v-fragile-bg);      color: var(--v-fragile-fg); }
.header .verdict.UNEVALUATED  { background: var(--v-unknown-bg);      color: var(--v-unknown-fg); }
.header .verdict.UNKNOWN      { background: var(--v-unknown-bg);      color: var(--v-unknown-fg); }

.tabs {
  display: flex; background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
}
.tab {
  padding: 12px 24px; cursor: pointer; border: none; background: none;
  font-size: 14px; font-weight: 500; color: var(--fg-muted);
  border-radius: 0;
}
.tab.active {
  background: var(--bg); color: var(--fg);
  border-bottom: 2px solid var(--accent);
}
.tab:hover { background: var(--bg-hover); }
.panel { display: none; padding: 20px 30px; }
.panel.active { display: block; }
.footer {
  padding: 20px 30px; color: var(--fg-dim); font-size: 11px;
  border-top: 1px solid var(--border); background: var(--bg-header);
}
"""


_SKELETON_RAW = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>$title</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
$theme_css
$page_css
</style>
</head>
<body>
<div class="header">
<h1>$title</h1>
<div class="meta">$meta</div>
</div>
<div class="tabs">
<button class="tab active" data-tab="performance">Performance</button>
<button class="tab" data-tab="trades">Trades</button>
<button class="tab" data-tab="robustness">Robustness</button>
<button class="tab" data-tab="parameters">Parameters</button>
</div>
<div id="performance" class="panel active">$performance_html</div>
<div id="trades" class="panel">$trades_html</div>
<div id="robustness" class="panel">$robustness_html</div>
<div id="parameters" class="panel">$parameters_html</div>
<div class="footer">$footer</div>
<script>
document.querySelectorAll('.tab').forEach(function(t) {
  t.addEventListener('click', function() {
    document.querySelectorAll('.tab').forEach(function(x) { x.classList.remove('active'); });
    document.querySelectorAll('.panel').forEach(function(x) { x.classList.remove('active'); });
    t.classList.add('active');
    document.getElementById(t.dataset.tab).classList.add('active');
  });
});

document.querySelectorAll('table.sortable').forEach(function(table) {
  var ths = table.querySelectorAll('thead th');
  ths.forEach(function(th, idx) {
    th.addEventListener('click', function() {
      var tbody = table.querySelector('tbody');
      var rows = Array.from(tbody.querySelectorAll('tr'));
      var dir = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';
      th.dataset.sortDir = dir;
      var first = rows[0] && rows[0].children[idx];
      var num = !isNaN(parseFloat((first && first.dataset.sort) || (first && first.textContent)));
      rows.sort(function(a, b) {
        var av = a.children[idx].dataset.sort || a.children[idx].textContent;
        var bv = b.children[idx].dataset.sort || b.children[idx].textContent;
        if (num) return (dir === 'asc' ? 1 : -1) * (parseFloat(av) - parseFloat(bv));
        return (dir === 'asc' ? 1 : -1) * av.localeCompare(bv);
      });
      rows.forEach(function(r) { tbody.appendChild(r); });
    });
  });
});
</script>
</body>
</html>
"""


_SKELETON_TMPL = Template(_SKELETON_RAW)


def render_dashboard(
    *,
    title: str,
    meta: str,
    performance_html: str,
    trades_html: str,
    robustness_html: str,
    parameters_html: str,
    footer: str,
) -> str:
    """Render the full per-run dashboard HTML with the dark theme baked in."""
    return _SKELETON_TMPL.substitute(
        title=title,
        meta=meta,
        performance_html=performance_html,
        trades_html=trades_html,
        robustness_html=robustness_html,
        parameters_html=parameters_html,
        footer=footer,
        theme_css=THEME_CSS,
        page_css=_PAGE_CSS,
    )


# Backwards-compat: older callers that still do HTML_SKELETON.format(...)
# won't work with Template, so we expose render_dashboard() as the public API.
# Leave HTML_SKELETON as None to fail fast if anything still imports it.
HTML_SKELETON = None
