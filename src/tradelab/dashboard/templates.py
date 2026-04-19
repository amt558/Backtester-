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
.header .meta {{ font-size: 13px; opacity: 0.8; margin-top: 4px; }}
.tabs {{ display: flex; background: #e8e8e8; border-bottom: 1px solid #ccc; }}
.tab {{ padding: 12px 24px; cursor: pointer; border: none; background: none;
        font-size: 14px; font-weight: 500; color: #555; }}
.tab.active {{ background: #fafafa; color: #000; border-bottom: 2px solid #2a7ae2; }}
.tab:hover {{ background: #f0f0f0; }}
.panel {{ display: none; padding: 20px 30px; }}
.panel.active {{ display: block; }}
.section {{ margin-bottom: 30px; }}
.section h2 {{ font-size: 16px; color: #444; margin-bottom: 10px; }}
.chart {{ background: white; border: 1px solid #e0e0e0; padding: 15px; border-radius: 4px; }}
.note {{ background: #fff8e0; padding: 12px 15px; border-left: 3px solid #f0c040;
         color: #555; font-size: 13px; margin: 15px 0; border-radius: 2px; }}
.footer {{ padding: 20px 30px; color: #888; font-size: 11px; border-top: 1px solid #e0e0e0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #f5f5f5; font-weight: 600; }}
</style>
</head>
<body>
<div class="header">
<h1>{title}</h1>
<div class="meta">{meta}</div>
</div>
<div class="tabs">
<button class="tab active" data-tab="performance">Performance</button>
<button class="tab" data-tab="robustness">Robustness</button>
<button class="tab" data-tab="parameters">Parameters</button>
</div>
<div id="performance" class="panel active">{performance_html}</div>
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
</script>
</body>
</html>
"""
