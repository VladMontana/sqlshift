"""Модуль генерации автономного интерактивного HTML-дашборда аудита SQL-запросов.

Создает самодостаточный (zero-dependency) HTML/CSS/JS отчет в современной темной теме
с интерактивными метриками, фильтрацией, поиском и side-by-side инспектором запросов.
"""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlshift.core.models import BatchAuditSummary


def generate_html_report(
    summary: BatchAuditSummary,
    title: str = "SQLShift — Database Audit Report",
) -> str:
    """Генерирует автономный интерактивный HTML-отчет на основе сводки аудита.

    Args:
        summary: Объект BatchAuditSummary с результатами анализа.
        title: Заголовок отчета.

    Returns:
        str: Полный HTML-код страницы со встроенными стилями и скриптами.
    """
    total = summary.total_queries
    pg_pct = round((summary.postgres_count / total * 100) if total > 0 else 0, 1)
    ch_pct = round((summary.clickhouse_count / total * 100) if total > 0 else 0, 1)

    low_c = summary.complexity_counts.get("low", 0)
    med_c = summary.complexity_counts.get("medium", 0)
    high_c = summary.complexity_counts.get("high", 0)

    # Подготавливаем JSON данных для клиентской фильтрации и инспектора
    items_data = []
    for it in summary.items:
        items_data.append(
            {
                "index": it.index,
                "original_sql": it.original_sql,
                "target": it.decision.target,
                "transpiled_sql": it.decision.sql,
                "is_analytical": it.decision.is_analytical,
                "complexity": it.decision.estimated_complexity,
                "reason": it.decision.reason,
                "bottlenecks": it.bottlenecks,
            }
        )
    items_json = json.dumps(items_data, ensure_ascii=False)

    bottleneck_badges_html = ""
    if summary.bottleneck_detected:
        for b_name, b_count in summary.bottleneck_detected.items():
            bottleneck_badges_html += (
                f'<span class="badge badge-warning">{html.escape(b_name)}: '
                f"<strong>{b_count}</strong></span> "
            )
    else:
        bottleneck_badges_html = (
            '<span class="badge badge-success">No critical bottlenecks found</span>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: rgba(18, 24, 38, 0.7);
      --card-border: rgba(255, 255, 255, 0.08);
      --card-hover: rgba(255, 255, 255, 0.12);
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --brand: #0d9488;
      --brand-glow: rgba(13, 148, 136, 0.35);
      --accent-pg: #38bdf8;
      --accent-ch: #fbbf24;
      --accent-high: #f43f5e;
      --accent-med: #fb923c;
      --accent-low: #34d399;
      --radius: 12px;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: radial-gradient(circle at 15% 15%, rgba(13, 148, 136, 0.15), transparent 40%),
                  radial-gradient(circle at 85% 85%, rgba(2, 132, 199, 0.12), transparent 45%),
                  var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
      min-height: 100vh;
      padding: 32px 24px;
      line-height: 1.5;
    }}

    .container {{
      max-width: 1360px;
      margin: 0 auto;
    }}

    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 32px;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      flex-wrap: wrap;
      gap: 16px;
    }}

    .logo-group {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}

    .logo-badge {{
      background: linear-gradient(135deg, #0d9488, #0284c7);
      color: #fff;
      font-weight: 800;
      font-size: 14px;
      padding: 8px 14px;
      border-radius: 8px;
      letter-spacing: 0.5px;
      box-shadow: 0 0 20px var(--brand-glow);
    }}

    h1 {{
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.5px;
    }}

    .subtitle {{
      color: var(--text-muted);
      font-size: 14px;
    }}

    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 18px;
      margin-bottom: 32px;
    }}

    .card {{
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 22px;
      transition: all 0.2s ease;
    }}

    .card:hover {{
      border-color: var(--card-hover);
      transform: translateY(-2px);
    }}

    .card-title {{
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      color: var(--text-muted);
      font-weight: 600;
      margin-bottom: 8px;
    }}

    .card-value {{
      font-size: 32px;
      font-weight: 800;
      letter-spacing: -1px;
    }}

    .card-detail {{
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 4px;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.3px;
    }}

    .badge-pg {{ background: rgba(56, 189, 248, 0.15); color: var(--accent-pg); border: 1px solid rgba(56, 189, 248, 0.3); }}
    .badge-ch {{ background: rgba(251, 191, 36, 0.15); color: var(--accent-ch); border: 1px solid rgba(251, 191, 36, 0.3); }}
    .badge-high {{ background: rgba(244, 63, 94, 0.15); color: var(--accent-high); border: 1px solid rgba(244, 63, 94, 0.3); }}
    .badge-medium {{ background: rgba(251, 146, 60, 0.15); color: var(--accent-med); border: 1px solid rgba(251, 146, 60, 0.3); }}
    .badge-low {{ background: rgba(52, 211, 153, 0.15); color: var(--accent-low); border: 1px solid rgba(52, 211, 153, 0.3); }}
    .badge-warning {{ background: rgba(251, 146, 60, 0.12); color: #fdba74; border: 1px solid rgba(251, 146, 60, 0.25); }}
    .badge-success {{ background: rgba(52, 211, 153, 0.12); color: #6ee7b7; border: 1px solid rgba(52, 211, 153, 0.25); }}

    .bottlenecks-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 20px 24px;
      margin-bottom: 32px;
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }}

    .controls-panel {{
      display: flex;
      gap: 16px;
      margin-bottom: 20px;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
    }}

    .search-input {{
      background: rgba(18, 24, 38, 0.8);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 10px 16px;
      color: var(--text);
      font-size: 14px;
      outline: none;
      min-width: 280px;
      flex: 1;
      max-width: 480px;
      transition: border-color 0.2s;
    }}

    .search-input:focus {{
      border-color: var(--brand);
    }}

    .filter-group {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}

    .filter-btn {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 13px;
      cursor: pointer;
      font-weight: 500;
      transition: all 0.15s;
    }}

    .filter-btn:hover, .filter-btn.active {{
      background: rgba(13, 148, 136, 0.2);
      border-color: var(--brand);
      color: #fff;
    }}

    .table-container {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      overflow: hidden;
      margin-bottom: 40px;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 14px;
    }}

    th {{
      background: rgba(255, 255, 255, 0.03);
      padding: 16px;
      font-weight: 600;
      color: var(--text-muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      border-bottom: 1px solid var(--card-border);
    }}

    td {{
      padding: 16px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      vertical-align: top;
    }}

    tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    code, pre {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 12.5px;
    }}

    .sql-preview {{
      max-width: 480px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: #cbd5e1;
    }}

    .btn-inspect {{
      background: rgba(13, 148, 136, 0.15);
      color: #2dd4bf;
      border: 1px solid rgba(13, 148, 136, 0.3);
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      transition: all 0.15s;
    }}

    .btn-inspect:hover {{
      background: var(--brand);
      color: #fff;
    }}

    /* Modal / Inspector */
    .modal-backdrop {{
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px);
      z-index: 1000;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}

    .modal-backdrop.open {{
      display: flex;
    }}

    .modal-content {{
      background: #0f172a;
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 16px;
      width: 100%;
      max-width: 1100px;
      max-height: 90vh;
      overflow-y: auto;
      padding: 32px;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    }}

    .modal-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
    }}

    .modal-close {{
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 24px;
      cursor: pointer;
      padding: 4px 8px;
    }}

    .modal-close:hover {{
      color: #fff;
    }}

    .side-by-side {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-bottom: 24px;
    }}

    @media (max-width: 800px) {{
      .side-by-side {{
        grid-template-columns: 1fr;
      }}
    }}

    .code-box {{
      background: #070b14;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      overflow: hidden;
    }}

    .code-box-header {{
      padding: 10px 16px;
      background: rgba(255, 255, 255, 0.03);
      border-bottom: 1px solid var(--card-border);
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .code-box pre {{
      padding: 16px;
      overflow-x: auto;
      color: #e2e8f0;
      line-height: 1.6;
    }}

    .copy-btn {{
      background: rgba(255, 255, 255, 0.08);
      border: none;
      color: var(--text-muted);
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 11px;
      cursor: pointer;
    }}

    .copy-btn:hover {{
      color: #fff;
      background: rgba(255, 255, 255, 0.16);
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="logo-group">
        <span class="logo-badge">SQLShift</span>
        <div>
          <h1>{html.escape(title)}</h1>
          <div class="subtitle">Cross-dialect SQL Router & AST Optimization Audit</div>
        </div>
      </div>
      <div>
        <span class="badge badge-pg">PostgreSQL OLTP: {pg_pct}%</span>
        <span class="badge badge-ch">ClickHouse OLAP: {ch_pct}%</span>
      </div>
    </header>

    <div class="stats-grid">
      <div class="card">
        <div class="card-title">Total Queries</div>
        <div class="card-value">{total}</div>
        <div class="card-detail">Parsed and profiled in batch</div>
      </div>
      <div class="card">
        <div class="card-title">PostgreSQL (OLTP)</div>
        <div class="card-value" style="color: var(--accent-pg);">{summary.postgres_count}</div>
        <div class="card-detail">{pg_pct}% of total workload</div>
      </div>
      <div class="card">
        <div class="card-title">ClickHouse (OLAP)</div>
        <div class="card-value" style="color: var(--accent-ch);">{summary.clickhouse_count}</div>
        <div class="card-detail">{ch_pct}% transpiled & accelerated</div>
      </div>
      <div class="card">
        <div class="card-title">Complexity Distribution</div>
        <div class="card-value" style="font-size: 20px; font-weight: 700; margin-top: 6px;">
          <span style="color: var(--accent-low)">{low_c} Low</span> / 
          <span style="color: var(--accent-med)">{med_c} Med</span> / 
          <span style="color: var(--accent-high)">{high_c} High</span>
        </div>
        <div class="card-detail">AST heuristic evaluation</div>
      </div>
    </div>

    <div class="bottlenecks-card">
      <strong style="font-size: 14px; color: var(--text);">Bottlenecks Detected:</strong>
      <div>{bottleneck_badges_html}</div>
    </div>

    <div class="controls-panel">
      <input type="text" id="searchInput" class="search-input" placeholder="Search queries by SQL or table name...">
      <div class="filter-group">
        <button class="filter-btn active" data-filter-target="all">All Targets</button>
        <button class="filter-btn" data-filter-target="postgresql">PostgreSQL</button>
        <button class="filter-btn" data-filter-target="clickhouse">ClickHouse</button>
      </div>
    </div>

    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th style="width: 50px;">#</th>
            <th>Original SQL</th>
            <th style="width: 140px;">Target</th>
            <th style="width: 120px;">Complexity</th>
            <th>Routing Reason</th>
            <th style="width: 110px;">Actions</th>
          </tr>
        </thead>
        <tbody id="tableBody">
          <!-- Rendered dynamically via JavaScript -->
        </tbody>
      </table>
    </div>
  </div>

  <!-- Inspector Modal -->
  <div class="modal-backdrop" id="modalBackdrop">
    <div class="modal-content">
      <div class="modal-header">
        <div>
          <h2 id="modalTitle" style="font-size: 18px; margin-bottom: 6px;">Query Inspector</h2>
          <div id="modalMeta" style="display: flex; gap: 8px;"></div>
        </div>
        <button class="modal-close" onclick="closeModal()">&times;</button>
      </div>

      <div class="side-by-side">
        <div class="code-box">
          <div class="code-box-header">
            <span>ORIGINAL (PostgreSQL Dialect)</span>
            <button class="copy-btn" onclick="copyCode('modalOriginal')">Copy</button>
          </div>
          <pre id="modalOriginal"></pre>
        </div>
        <div class="code-box">
          <div class="code-box-header">
            <span id="modalTargetLabel">TRANSPILED (ClickHouse Dialect)</span>
            <button class="copy-btn" onclick="copyCode('modalTranspiled')">Copy</button>
          </div>
          <pre id="modalTranspiled"></pre>
        </div>
      </div>

      <div id="modalBottlenecks" style="margin-top: 16px;"></div>
    </div>
  </div>

  <script>
    const queries = {items_json};
    let activeTarget = 'all';
    let searchQuery = '';

    const tableBody = document.getElementById('tableBody');
    const searchInput = document.getElementById('searchInput');

    function renderTable() {{
      const filtered = queries.filter(q => {{
        const matchesTarget = activeTarget === 'all' || q.target === activeTarget;
        const matchesSearch = !searchQuery || 
          q.original_sql.toLowerCase().includes(searchQuery.toLowerCase()) ||
          q.reason.toLowerCase().includes(searchQuery.toLowerCase());
        return matchesTarget && matchesSearch;
      }});

      if (filtered.length === 0) {{
        tableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 32px;">No matching queries found.</td></tr>';
        return;
      }}

      tableBody.innerHTML = filtered.map(q => {{
        const targetBadge = q.target === 'clickhouse' 
          ? '<span class="badge badge-ch">ClickHouse (OLAP)</span>' 
          : '<span class="badge badge-pg">PostgreSQL (OLTP)</span>';
        
        let compBadge = '<span class="badge badge-low">LOW</span>';
        if (q.complexity === 'high') compBadge = '<span class="badge badge-high">HIGH</span>';
        else if (q.complexity === 'medium') compBadge = '<span class="badge badge-medium">MEDIUM</span>';

        return `
          <tr>
            <td style="color: var(--text-muted); font-weight: 600;">${{q.index}}</td>
            <td>
              <div class="sql-preview"><code>${{escapeHtml(q.original_sql)}}</code></div>
            </td>
            <td>${{targetBadge}}</td>
            <td>${{compBadge}}</td>
            <td style="color: var(--text-muted); font-size: 13px;">${{escapeHtml(q.reason)}}</td>
            <td>
              <button class="btn-inspect" onclick="openModal(${{q.index}})">Inspect</button>
            </td>
          </tr>
        `;
      }}).join('');
    }}

    function escapeHtml(str) {{
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }}

    searchInput.addEventListener('input', (e) => {{
      searchQuery = e.target.value.trim();
      renderTable();
    }});

    document.querySelectorAll('.filter-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        activeTarget = btn.getAttribute('data-filter-target');
        renderTable();
      }});
    }});

    function openModal(index) {{
      const item = queries.find(q => q.index === index);
      if (!item) return;

      document.getElementById('modalTitle').textContent = `Query #${{item.index}} Details`;
      document.getElementById('modalOriginal').textContent = item.original_sql;
      document.getElementById('modalTranspiled').textContent = item.transpiled_sql;

      const targetLabel = item.target === 'clickhouse' ? 'TRANSPILED (ClickHouse Dialect)' : 'EXECUTED (PostgreSQL Dialect)';
      document.getElementById('modalTargetLabel').textContent = targetLabel;

      let metaHtml = item.target === 'clickhouse' 
        ? '<span class="badge badge-ch">ClickHouse OLAP</span>' 
        : '<span class="badge badge-pg">PostgreSQL OLTP</span>';
      metaHtml += ` <span class="badge badge-${{item.complexity}}">${{item.complexity.toUpperCase()}}</span>`;
      document.getElementById('modalMeta').innerHTML = metaHtml;

      const bDiv = document.getElementById('modalBottlenecks');
      if (item.bottlenecks && item.bottlenecks.length > 0) {{
        bDiv.innerHTML = '<strong style="font-size: 13px; color: #fdba74;">Detected Bottlenecks:</strong> ' + 
          item.bottlenecks.map(b => `<span class="badge badge-warning">${{escapeHtml(b)}}</span>`).join(' ');
      }} else {{
        bDiv.innerHTML = '<span class="badge badge-success">No AST Bottlenecks detected in this query.</span>';
      }}

      document.getElementById('modalBackdrop').classList.add('open');
    }}

    function closeModal() {{
      document.getElementById('modalBackdrop').classList.remove('open');
    }}

    window.onclick = function(event) {{
      const modal = document.getElementById('modalBackdrop');
      if (event.target === modal) {{
        closeModal();
      }}
    }};

    function copyCode(elementId) {{
      const text = document.getElementById(elementId).textContent;
      navigator.clipboard.writeText(text);
    }}

    renderTable();
  </script>
</body>
</html>
"""
