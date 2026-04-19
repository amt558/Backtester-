"""HTML skeleton with tab switcher."""

HTML_SKELETON = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; background: #fafafa; color: #222; }}
.header {{ padding: 20px 30px; background: #1a1a1a; color: #fafafa; }}
.header h1 {{ margin: 0; font-size: 22px; }}
.header .meta {{ font-size: 13px; opacity: 0.85; margin-top: 6px; line-height: 1.5; }}
.header .verdict {{ display: inline-block; padding: 4px 12px; border-radius: 4px;
                    font-weight: 700; font-size: 13px; margin-right: 8px; }}
.header .verdict.ROBUST {{ background: #2d9c3a; color: white; }}
.header .verdict.INCONCLUSIVE {{ background: #d6a02a; color: white; }}
.header .verdict.FRAGILE {{ background: #d0443e; color: white; }}
.header .verdict.UNKNOWN {{ background: #666; color: white; }}
.tabs {{ display: flex; background: #e8e8e8; border-bottom: 1px solid #ccc; }}
.tab {{ padding: 12px 24px; cursor: pointer; border: none; background: none;
        font-size: 14px; font-weight: 500; color: #555; }}
.tab.active {{ background: #fafafa; color: #000; border-bottom: 2px solid #2a7ae2; }}
.tab:hover {{ background: #f0f0f0; }}
.panel {{ display: none; padding: 20px 30px; }}
.panel.active {{ display: block; }}
.section {{ margin-bottom: 30px; }}
.section h2 {{ font-size: 16px; color: #444; margin-bottom: 10px; }}
.section h3 {{ font-size: 14px; color: #555; margin: 16px 0 6px; }}
.chart {{ background: white; border: 1px solid #e0e0e0; padding: 15px; border-radius: 4px; }}
.note {{ background: #fff8e0; padding: 12px 15px; border-left: 3px solid #f0c040;
         color: #555; font-size: 13px; margin: 15px 0; border-radius: 2px; }}
.footer {{ padding: 20px 30px; color: #888; font-size: 11px; border-top: 1px solid #e0e0e0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #f5f5f5; font-weight: 600; cursor: pointer; user-select: none; }}
th:hover {{ background: #ebebeb; }}
.win {{ color: #2d9c3a; }}
.loss {{ color: #d0443e; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
             gap: 12px; margin: 12px 0; }}
.kpi {{ background: white; border: 1px solid #e0e0e0; border-radius: 6px;
        padding: 10px 14px; }}
.kpi .label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.04em; }}
.kpi .value {{ font-size: 20px; font-weight: 600; margin-top: 4px; }}
.dual-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 900px) {{ .dual-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="header">
<h1>{title}</h1>
<div class="meta">{meta}</div>
</div>
<div class="tabs">
<button class="tab active" data-tab="performance">Performance</button>
<button class="tab" data-tab="trades">Trades</button>
<button class="tab" data-tab="robustness">Robustness</button>
<button class="tab" data-tab="parameters">Parameters</button>
</div>
<div id="performance" class="panel active">{performance_html}</div>
<div id="trades" class="panel">{trades_html}</div>
<div id="robustness" class="panel">{robustness_html}</div>
<div id="parameters" class="panel">{parameters_html}</div>
<div class="footer">{footer}</div>
<script>
document.querySelectorAll('.tab').forEach(t => {{
  t.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById(t.dataset.tab).classList.add('active');
  }});
}});

// Lightweight table sort: click any <th> in a sortable table to toggle
document.querySelectorAll('table.sortable').forEach(table => {{
  const ths = table.querySelectorAll('thead th');
  ths.forEach((th, idx) => {{
    th.addEventListener('click', () => {{
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const dir = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';
      th.dataset.sortDir = dir;
      const num = !isNaN(parseFloat(rows[0]?.children[idx]?.dataset.sort ?? rows[0]?.children[idx]?.textContent));
      rows.sort((a, b) => {{
        const av = a.children[idx].dataset.sort ?? a.children[idx].textContent;
        const bv = b.children[idx].dataset.sort ?? b.children[idx].textContent;
        if (num) return (dir === 'asc' ? 1 : -1) * (parseFloat(av) - parseFloat(bv));
        return (dir === 'asc' ? 1 : -1) * av.localeCompare(bv);
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
}});
</script>
</body>
</html>
"""
