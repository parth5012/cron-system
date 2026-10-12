"""
Homepage rendering module for Cron System.
Provides an organized, uncluttered hub separating Main Applications from Categorized Static Content and Asset Sharing.
"""

import html
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROUTER_OWNED_SLUGS = {"wayfinder", "antigravity", "pull-requests", "email-triage", "pwa"}

MAIN_PAGES = [
    {
        "id": "wayfinder",
        "title": "Wayfinder",
        "badge": "Core Initiative",
        "badge_color": "sky",
        "icon": "🧭",
        "url": "/wayfinder",
        "description": "Project & execution navigator, roadmap milestones, and active initiative ticket tracking.",
        "category": "app",
    },
    {
        "id": "antigravity",
        "title": "Antigravity Limits",
        "badge": "Quota & Limits",
        "badge_color": "amber",
        "icon": "⚡",
        "url": "/antigravity",
        "description": "Multi-account LLM quota tracker, Google Cloud Code rate limits, cooldowns & token metrics.",
        "category": "app",
    },
    {
        "id": "pull-requests",
        "title": "Pull Requests",
        "badge": "Code Review",
        "badge_color": "purple",
        "icon": "🔀",
        "url": "/pull-requests",
        "description": "GitHub PR review dashboard, active branch monitoring, and automated diff inspection.",
        "category": "app",
    },
    {
        "id": "email-triage",
        "title": "Email Triage",
        "badge": "Inbox AI",
        "badge_color": "emerald",
        "icon": "📬",
        "url": "/email-triage",
        "description": "Himalaya CLI inbox automation with TypeSafe Jev & Clef System 1 decision models.",
        "category": "app",
    },
    {
        "id": "pwa",
        "title": "Cron App (PWA)",
        "badge": "Mobile Shell",
        "badge_color": "indigo",
        "icon": "📱",
        "url": "/pwa/",
        "description": "Installable Progressive Web App shell with offline caching, mobile navigation, and app icons.",
        "category": "app",
    },
    {
        "id": "cron-jobs",
        "title": "Engine & Cron Jobs",
        "badge": "Background Daemon",
        "badge_color": "slate",
        "icon": "⚙️",
        "url": "/api/jobs",
        "description": "Background cron tasks, automated job schedules, execution logs, and runner status.",
        "category": "app",
    },
]

CATEGORIES = [
    {"id": "all", "name": "All Files", "icon": "📂"},
    {"id": "reports", "name": "Decks & Reports", "icon": "📑"},
    {"id": "content", "name": "Articles & Guides", "icon": "✍️"},
    {"id": "orca", "name": "Marine & Research", "icon": "🌊"},
    {"id": "tools", "name": "Tools & Workflows", "icon": "🛠️"},
    {"id": "ui", "name": "UI & Assets", "icon": "🎨"},
    {"id": "uploads", "name": "Uploads & Shared", "icon": "📦"},
]


def categorize_slug(slug: str) -> Tuple[str, str, str]:
    slug_lower = slug.lower()
    if slug_lower.startswith("content-"):
        return ("content", "Articles & Guides", "✍️")
    elif any(k in slug_lower for k in ["deck", "harness", "arch", "report", "findings"]):
        return ("reports", "Decks & Reports", "📑")
    elif any(k in slug_lower for k in ["orca", "marine", "pfz", "ncmrwf"]):
        return ("orca", "Marine & Research", "🌊")
    elif any(k in slug_lower for k in ["polybar", "glyph", "icon", "theme"]):
        return ("ui", "UI & Assets", "🎨")
    elif any(k in slug_lower for k in ["bid", "prompter", "review", "tool"]):
        return ("tools", "Tools & Workflows", "🛠️")
    elif slug_lower == "uploads":
        return ("uploads", "Uploads & Shared", "📦")
    return ("other", "Other Hosted", "📁")


def extract_dir_meta(sub_path: Path) -> Dict[str, Any]:
    slug = sub_path.name
    files = [f for f in sub_path.rglob("*") if f.is_file()]
    total_bytes = sum(f.stat().st_size for f in files)
    
    size_mb = total_bytes / (1024 * 1024)
    size_kb = total_bytes / 1024
    formatted_size = (
        f"{size_mb:.2f} MB" if total_bytes > 1024 * 1024 else f"{size_kb:.2f} KB"
    )
    
    cat_id, cat_name, cat_icon = categorize_slug(slug)
    
    title = ""
    idx = sub_path / "index.html"
    if idx.exists():
        try:
            content = idx.read_text(errors="ignore")
            m = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
            if m:
                t = html.unescape(m.group(1).strip())
                t = re.sub(
                    r"\s*([|—–-]\s*(Social Content.*|Hermes Agent.*|glyph browser.*|Draft.*)?)$",
                    "",
                    t,
                ).strip()
                title = t
        except Exception:
            pass
            
    if not title:
        title = slug.replace("content-", "").replace("-", " ").title()

    exts = sorted(list(set(f.suffix.lower().lstrip(".") for f in files if f.suffix)))[:3]
    exts_str = " • ".join(e.upper() for e in exts) if exts else "FILES"

    return {
        "slug": slug,
        "title": title,
        "category_id": cat_id,
        "category_name": cat_name,
        "category_icon": cat_icon,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "total_size": formatted_size,
        "exts": exts_str,
        "url": f"/{slug}",
    }


def render_homepage(static_dir: Path) -> str:
    directories: List[Dict[str, Any]] = []
    total_files = 0
    total_bytes_all = 0
    
    if static_dir.exists():
        for sub in sorted(static_dir.iterdir()):
            if sub.is_dir() and sub.name not in ROUTER_OWNED_SLUGS:
                meta = extract_dir_meta(sub)
                directories.append(meta)
                total_files += meta["file_count"]
                total_bytes_all += meta["total_bytes"]

    total_mb = total_bytes_all / (1024 * 1024)
    total_label = (
        f"{total_mb:.2f} MB" if total_bytes_all > 1024 * 1024
        else f"{total_bytes_all / 1024:.2f} KB"
    )

    # Category counts
    cat_counts: Dict[str, int] = {}
    for d in directories:
        cat_counts[d["category_id"]] = cat_counts.get(d["category_id"], 0) + 1

    # Render Main Apps Cards
    main_cards_html = "".join([
        f"""
        <div class="main-card" data-app-id="{html.escape(app['id'])}" data-search="{html.escape(app['title'])} {html.escape(app['description'])}">
            <div class="main-card-header">
                <span class="main-icon">{app['icon']}</span>
                <span class="badge badge-{app['badge_color']}">{html.escape(app['badge'])}</span>
            </div>
            <h3 class="main-title">{html.escape(app['title'])}</h3>
            <p class="main-desc">{html.escape(app['description'])}</p>
            <div class="card-actions">
                <a class="btn btn-primary" href="{html.escape(app['url'])}">Launch App ↗</a>
                <button class="btn btn-ghost" data-copy-url="{html.escape(app['url'])}">Copy link</button>
            </div>
        </div>
        """
        for app in MAIN_PAGES
    ])

    # Render Static Directory Cards
    dirs_html = "".join([
        f"""
        <div class="dir-card" data-slug="{html.escape(d['slug'])}" data-category="{html.escape(d['category_id'])}" data-search="{html.escape(d['title'])} {html.escape(d['slug'])} {html.escape(d['category_name'])}">
            <div class="dir-card-header">
                <span class="category-pill">{d['category_icon']} {html.escape(d['category_name'])}</span>
                <span class="ext-pill">{html.escape(d['exts'])}</span>
            </div>
            <h3 class="dir-title"><a href="{html.escape(d['url'])}">{html.escape(d['title'])}</a></h3>
            <div class="slug-badge"><code>/{html.escape(d['slug'])}</code></div>
            <p class="dir-meta">{d['file_count']} files • {d['total_size']}</p>
            <div class="card-actions">
                <a class="btn" href="{html.escape(d['url'])}">Open ↗</a>
                <button class="btn ghost" data-copy-url="{html.escape(d['url'])}">Copy link</button>
            </div>
        </div>
        """
        for d in directories
    ]) or "<p class='empty'>No hosted directories yet — upload assets below.</p>"

    # Render Category Filter Pills
    filter_pills_html = []
    # All button
    filter_pills_html.append(
        f'<button class="filter-btn active" data-filter="all">All <span class="filter-count">{len(directories)}</span></button>'
    )
    for cat in CATEGORIES:
        if cat["id"] == "all":
            continue
        count = cat_counts.get(cat["id"], 0)
        if count > 0:
            filter_pills_html.append(
                f'<button class="filter-btn" data-filter="{cat["id"]}">{cat["icon"]} {html.escape(cat["name"])} <span class="filter-count">{count}</span></button>'
            )
    categories_html = "".join(filter_pills_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>⚡ Cron System - AI-OS Hub & Content Gateway</title>
    <link rel="icon" type="image/svg+xml" href="/icons/ghost.svg">
    <style>
        :root {{
            --bg: #0b0f19;
            --bg-surface: #111827;
            --bg-elevated: #1a2234;
            --border: #1f293d;
            --border-hover: #38bdf8;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --text-dim: #64748b;
            --primary: #38bdf8;
            --primary-hover: #0284c7;
            --primary-glow: rgba(56, 189, 248, 0.15);
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --radius-sm: 8px;
            --radius-md: 12px;
            --radius-lg: 16px;
            --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}
        @media (prefers-color-scheme: light) {{
            :root {{
                --bg: #f8fafc;
                --bg-surface: #ffffff;
                --bg-elevated: #f1f5f9;
                --border: #e2e8f0;
                --border-hover: #0284c7;
                --text-main: #0f172a;
                --text-muted: #64748b;
                --text-dim: #94a3b8;
                --primary: #0284c7;
                --primary-hover: #0369a1;
                --primary-glow: rgba(2, 132, 199, 0.12);
            }}
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: var(--font);
            background: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            padding: 24px 16px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1120px;
            margin: 0 auto;
        }}

        /* Header */
        header.top-header {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
        }}
        .brand-group {{
            display: flex;
            align-items: center;
            gap: 14px;
        }}
        .brand-icon {{
            font-size: 2rem;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            width: 52px;
            height: 52px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }}
        .brand-text h1 {{
            font-size: 1.65rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: var(--text-main);
        }}
        .brand-text p {{
            font-size: 0.88rem;
            color: var(--text-muted);
            margin-top: 2px;
        }}
        .header-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
        }}
        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(16, 185, 129, 0.1);
            color: var(--success);
            border: 1px solid rgba(16, 185, 129, 0.25);
            padding: 6px 12px;
            border-radius: 999px;
            font-size: 0.82rem;
            font-weight: 600;
        }}
        .status-pulse {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
            box-shadow: 0 0 8px var(--success);
        }}
        .stats-summary {{
            font-size: 0.85rem;
            color: var(--text-muted);
            background: var(--bg-surface);
            border: 1px solid var(--border);
            padding: 6px 14px;
            border-radius: 999px;
        }}

        /* Navigation Switcher Tabs */
        .view-switcher {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 20px;
            padding: 4px;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            width: fit-content;
        }}
        .view-tab {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 8px 16px;
            border-radius: var(--radius-sm);
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .view-tab:hover {{
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.05);
        }}
        .view-tab.active {{
            background: var(--primary);
            color: #000;
            box-shadow: 0 2px 8px var(--primary-glow);
        }}

        /* Search Toolbar */
        .toolbar {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 28px;
            position: relative;
        }}
        .search-wrapper {{
            position: relative;
            flex: 1;
        }}
        .search-icon {{
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-dim);
            pointer-events: none;
            font-size: 1rem;
        }}
        input[type="search"] {{
            width: 100%;
            font-size: 0.95rem;
            padding: 12px 14px 12px 42px;
            border-radius: var(--radius-md);
            border: 1px solid var(--border);
            background: var(--bg-surface);
            color: var(--text-main);
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}
        input[type="search"]:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-glow);
        }}
        .search-hint {{
            position: absolute;
            right: 14px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 0.75rem;
            color: var(--text-dim);
            background: var(--bg-elevated);
            border: 1px solid var(--border);
            padding: 2px 6px;
            border-radius: 4px;
            pointer-events: none;
        }}

        /* Sections */
        .section-block {{
            margin-bottom: 36px;
        }}
        .section-header {{
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 16px;
        }}
        .section-title {{
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .section-subtitle {{
            font-size: 0.85rem;
            color: var(--text-muted);
        }}

        /* Main Applications Grid */
        .main-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 16px;
        }}
        .main-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 20px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
            position: relative;
            overflow: hidden;
        }}
        .main-card:hover {{
            transform: translateY(-2px);
            border-color: var(--primary);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
        }}
        .main-card-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
        }}
        .main-icon {{
            font-size: 1.75rem;
            width: 44px;
            height: 44px;
            border-radius: var(--radius-sm);
            background: var(--bg-elevated);
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid var(--border);
        }}
        .badge {{
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 4px 10px;
            border-radius: 999px;
            border: 1px solid transparent;
        }}
        .badge-sky {{ background: rgba(56, 189, 248, 0.12); color: #38bdf8; border-color: rgba(56, 189, 248, 0.3); }}
        .badge-amber {{ background: rgba(245, 158, 11, 0.12); color: #f59e0b; border-color: rgba(245, 158, 11, 0.3); }}
        .badge-purple {{ background: rgba(168, 85, 247, 0.12); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }}
        .badge-emerald {{ background: rgba(16, 185, 129, 0.12); color: #34d399; border-color: rgba(16, 185, 129, 0.3); }}
        .badge-indigo {{ background: rgba(99, 102, 241, 0.12); color: #818cf8; border-color: rgba(99, 102, 241, 0.3); }}
        .badge-slate {{ background: rgba(148, 163, 184, 0.12); color: #cbd5e1; border-color: rgba(148, 163, 184, 0.3); }}

        .main-title {{
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 6px;
        }}
        .main-desc {{
            font-size: 0.88rem;
            color: var(--text-muted);
            line-height: 1.45;
            margin-bottom: 16px;
            flex-grow: 1;
        }}

        /* Buttons & Actions */
        .card-actions {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: auto;
        }}
        .btn {{
            appearance: none;
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            background: var(--bg-elevated);
            color: var(--text-main);
            padding: 8px 14px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            transition: all 0.15s ease;
        }}
        .btn:hover {{
            border-color: var(--primary);
            color: var(--primary);
            background: var(--bg-surface);
        }}
        .btn-primary {{
            background: var(--primary);
            color: #000;
            border-color: var(--primary);
        }}
        .btn-primary:hover {{
            background: var(--primary-hover);
            border-color: var(--primary-hover);
            color: #fff;
        }}
        .btn.ghost, .btn-ghost {{
            background: transparent;
            color: var(--text-muted);
        }}
        .btn.ghost:hover, .btn-ghost:hover {{
            color: var(--text-main);
            border-color: var(--border);
            background: var(--bg-elevated);
        }}

        /* Category Filter Pills */
        .category-filter {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 18px;
        }}
        .filter-btn {{
            background: var(--bg-surface);
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 6px 12px;
            border-radius: 999px;
            font-size: 0.82rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .filter-btn:hover {{
            border-color: var(--primary);
            color: var(--text-main);
        }}
        .filter-btn.active {{
            background: rgba(56, 189, 248, 0.12);
            border-color: var(--primary);
            color: var(--primary);
            font-weight: 600;
        }}
        .filter-count {{
            font-size: 0.75rem;
            opacity: 0.8;
            background: var(--bg-elevated);
            padding: 1px 6px;
            border-radius: 999px;
        }}

        /* Static Directories Grid */
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
            gap: 14px;
        }}
        .dir-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 16px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: border-color 0.15s ease, transform 0.15s ease;
        }}
        .dir-card:hover {{
            border-color: var(--primary);
            transform: translateY(-2px);
        }}
        .dir-card-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 8px;
        }}
        .category-pill {{
            font-size: 0.72rem;
            font-weight: 600;
            color: var(--text-muted);
            background: var(--bg-elevated);
            padding: 2px 8px;
            border-radius: 6px;
        }}
        .ext-pill {{
            font-size: 0.68rem;
            font-family: var(--font-mono);
            color: var(--primary);
            opacity: 0.85;
            font-weight: 600;
        }}
        .dir-title {{
            font-size: 0.96rem;
            font-weight: 600;
            line-height: 1.35;
            margin-bottom: 4px;
            overflow-wrap: anywhere;
        }}
        .dir-title a {{
            color: var(--text-main);
            text-decoration: none;
            transition: color 0.15s ease;
        }}
        .dir-title a:hover {{
            color: var(--primary);
        }}
        .slug-badge {{
            margin-bottom: 8px;
        }}
        .slug-badge code {{
            font-family: var(--font-mono);
            font-size: 0.75rem;
            color: var(--text-dim);
            background: rgba(0, 0, 0, 0.2);
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .dir-meta {{
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-bottom: 14px;
        }}

        /* Dropzone & Upload */
        #dropzone {{
            border: 2px dashed var(--border);
            border-radius: var(--radius-md);
            padding: 32px 20px;
            text-align: center;
            background: var(--bg-surface);
            cursor: pointer;
            transition: border-color 0.2s, background-color 0.2s;
        }}
        #dropzone:hover, #dropzone.dragover {{
            border-color: var(--primary);
            background: var(--bg-elevated);
        }}
        #status {{
            margin-top: 12px;
            font-weight: 600;
            font-size: 0.9rem;
        }}
        #uploadList, #recentList {{
            list-style: none;
            padding: 0;
            margin: 14px 0;
            display: grid;
            gap: 10px;
        }}
        #uploadList li, #recentList li {{
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 10px 14px;
            font-size: 0.88rem;
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
            justify-content: space-between;
        }}
        .file-name {{
            overflow-wrap: anywhere;
            flex: 1 1 220px;
            display: flex;
            align-items: center;
            gap: 6px;
            font-weight: 500;
        }}
        .file-actions {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .empty {{
            opacity: 0.7;
            font-size: 0.9rem;
            color: var(--text-muted);
            margin: 8px 0;
        }}

        /* Responsive Adjustments */
        @media (max-width: 768px) {{
            body {{ padding: 16px 12px; }}
            .brand-text h1 {{ font-size: 1.4rem; }}
            .main-grid {{ grid-template-columns: 1fr; }}
            .grid {{ grid-template-columns: 1fr; }}
            .view-switcher {{ width: 100%; }}
            .view-tab {{ flex: 1; justify-content: center; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Top Header -->
        <header class="top-header">
            <div class="brand-group">
                <div class="brand-icon">⚡</div>
                <div class="brand-text">
                    <h1>Cron System Hub</h1>
                    <p>AI-OS Central Orchestrator &amp; Static Gateway</p>
                </div>
            </div>
            <div class="header-meta">
                <span class="status-badge"><span class="status-pulse"></span> Online</span>
                <span class="stats-summary">{len(directories)} Static Folders • {total_files} Files • {total_label}</span>
            </div>
        </header>

        <!-- View Navigation Tabs -->
        <nav class="view-switcher" role="tablist">
            <button class="view-tab active" data-view="all" role="tab">🌟 All Overview</button>
            <button class="view-tab" data-view="main" role="tab">🚀 Main Pages ({len(MAIN_PAGES)})</button>
            <button class="view-tab" data-view="static" role="tab">📁 Static Files ({len(directories)})</button>
            <button class="view-tab" data-view="upload" role="tab">☁️ Upload &amp; Share</button>
        </nav>

        <!-- Search Toolbar -->
        <div class="toolbar">
            <div class="search-wrapper">
                <span class="search-icon">🔍</span>
                <input type="search" id="dirSearch" placeholder="Search main apps, static reports, articles, uploads…" aria-label="Search folders and recent uploads">
                <span class="search-hint">/</span>
            </div>
        </div>

        <!-- Section 1: Main Pages -->
        <section id="mainPagesSection" class="section-block">
            <div class="section-header">
                <h2 class="section-title">🚀 Main Applications &amp; Core Pages</h2>
                <span class="section-subtitle">Interactive dashboards, decision engines, and limit trackers</span>
            </div>
            <div class="main-grid" id="mainGrid">
                {main_cards_html}
            </div>
        </section>

        <!-- Section 2: Static Files & Hosted Content -->
        <section id="staticFilesSection" class="section-block">
            <div class="section-header">
                <h2 class="section-title">📁 Static Files &amp; Hosted Content</h2>
                <span class="section-subtitle">Slide decks, articles, research reports, and static UI assets</span>
            </div>

            <!-- Category Filter Pills -->
            <div class="category-filter" id="categoryFilter">
                {categories_html}
            </div>

            <!-- Directories Grid -->
            <div class="grid" id="dirGrid">
                {dirs_html}
            </div>
        </section>

        <!-- Section 3: Upload & Share -->
        <section id="uploadSection" class="section-block">
            <div class="section-header">
                <h2 class="section-title">☁️ Upload &amp; Share Assets</h2>
                <span class="section-subtitle">Instantly host and share presentation decks, images, and documents</span>
            </div>

            <div id="dropzone">
                <p><strong>Drag &amp; drop files here or click to select</strong> (multiple allowed)</p>
                <p style="font-size: 0.85em; opacity: 0.75; margin-top: 6px;">
                    Max 50MB each. HTML, PDF, PPT / PPTX, DOC / DOCX, XLS / XLSX, CSV, TXT, Images, Audio, Video, ZIP
                </p>
                <input type="file" id="fileInput" style="display: none;" multiple>
            </div>
            <div id="status" role="status"></div>
            <ul id="uploadList"></ul>

            <h2 style="font-size: 1.15rem; font-weight: 700; margin-top: 24px; margin-bottom: 8px;">Recent uploads</h2>
            <p class="empty" id="recentEmpty">Latest shareable files from /uploads — View, Download, or Copy link to share anywhere.</p>
            <ul id="recentList"></ul>
        </section>
    </div>

    <script>
        const dropzone = document.getElementById('dropzone');
        const fileInput = document.getElementById('fileInput');
        const status = document.getElementById('status');
        const uploadList = document.getElementById('uploadList');
        const recentList = document.getElementById('recentList');
        const recentEmpty = document.getElementById('recentEmpty');
        const dirSearch = document.getElementById('dirSearch');
        const viewTabs = document.querySelectorAll('.view-tab');
        const filterBtns = document.querySelectorAll('.filter-btn');
        const mainSection = document.getElementById('mainPagesSection');
        const staticSection = document.getElementById('staticFilesSection');
        const uploadSection = document.getElementById('uploadSection');

        let currentView = 'all';
        let currentFilter = 'all';

        function esc(s) {{
            return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
        }}

        // Copy Link Helper with Visual Toast
        async function copyText(text, btn) {{
            try {{
                await navigator.clipboard.writeText(text);
            }} catch (e) {{
                const ta = document.createElement('textarea');
                ta.value = text;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                ta.remove();
            }}
            if (btn) {{
                const old = btn.textContent;
                btn.textContent = 'Copied!';
                btn.style.color = '#10b981';
                setTimeout(() => {{
                    btn.textContent = old;
                    btn.style.color = '';
                }}, 1500);
            }}
        }}

        document.addEventListener('click', (e) => {{
            const btn = e.target.closest('[data-copy-url]');
            if (btn) {{
                const rel = btn.getAttribute('data-copy-url');
                copyText(new URL(rel, location.origin).href, btn);
            }}
        }});

        // View Mode Switcher
        function setView(view) {{
            currentView = view;
            viewTabs.forEach(t => t.classList.toggle('active', t.getAttribute('data-view') === view));
            
            if (view === 'all') {{
                mainSection.style.display = '';
                staticSection.style.display = '';
                uploadSection.style.display = '';
            }} else if (view === 'main') {{
                mainSection.style.display = '';
                staticSection.style.display = 'none';
                uploadSection.style.display = 'none';
            }} else if (view === 'static') {{
                mainSection.style.display = 'none';
                staticSection.style.display = '';
                uploadSection.style.display = 'none';
            }} else if (view === 'upload') {{
                mainSection.style.display = 'none';
                staticSection.style.display = 'none';
                uploadSection.style.display = '';
            }}
            applyFilters();
        }}

        viewTabs.forEach(tab => {{
            tab.addEventListener('click', () => {{
                const view = tab.getAttribute('data-view');
                setView(view);
                if (history.replaceState) {{
                    history.replaceState(null, null, '#' + view);
                }}
            }});
        }});

        // URL hash sync
        if (location.hash) {{
            const h = location.hash.replace('#', '');
            if (['all', 'main', 'static', 'upload'].includes(h)) {{
                setView(h);
            }}
        }}

        // Category Filter
        filterBtns.forEach(btn => {{
            btn.addEventListener('click', () => {{
                filterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentFilter = btn.getAttribute('data-filter');
                applyFilters();
            }});
        }});

        // Search & Filter Application
        function applyFilters() {{
            const q = dirSearch ? dirSearch.value.trim().toLowerCase() : '';

            // Main cards
            document.querySelectorAll('#mainGrid .main-card').forEach(card => {{
                const searchTxt = (card.getAttribute('data-search') || card.textContent).toLowerCase();
                const matchesSearch = !q || searchTxt.includes(q);
                card.style.display = matchesSearch ? '' : 'none';
            }});

            // Static directory cards
            document.querySelectorAll('#dirGrid .dir-card').forEach(card => {{
                const searchTxt = (card.getAttribute('data-search') || card.textContent).toLowerCase();
                const category = card.getAttribute('data-category');
                const matchesSearch = !q || searchTxt.includes(q);
                const matchesCategory = currentFilter === 'all' || category === currentFilter;
                card.style.display = (matchesSearch && matchesCategory) ? '' : 'none';
            }});

            // Recent and upload lists
            document.querySelectorAll('#recentList li, #uploadList li').forEach(li => {{
                const matchesSearch = !q || li.textContent.toLowerCase().includes(q);
                li.style.display = matchesSearch ? '' : 'none';
            }});
        }}

        if (dirSearch) {{
            dirSearch.addEventListener('input', applyFilters);
        }}

        // Shortcut: '/' focuses search
        document.addEventListener('keydown', (e) => {{
            if (e.key === '/' && document.activeElement !== dirSearch && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {{
                e.preventDefault();
                dirSearch.focus();
            }}
        }});

        // Load Recent Uploads
        async function loadRecent() {{
            try {{
                const res = await fetch('/admin/static/uploads/status');
                if (!res.ok) return;
                const data = await res.json();
                const files = (data.files || []).slice(0, 15);
                if (!files.length) return;
                if (recentEmpty) recentEmpty.style.display = 'none';
                recentList.innerHTML = files.map(f => {{
                    const url = '/uploads/' + encodeURIComponent(f.name).replace(/%2F/g, '/');
                    return '<li><span class=\"file-name\">📄 ' + esc(f.name) + '</span>'
                        + '<span class=\"file-actions\">'
                        + '<a class=\"btn\" href=\"' + esc(url) + '\" target=\"_blank\" rel=\"noopener\">View ↗</a>'
                        + '<a class=\"btn ghost\" href=\"' + esc(url) + '\" download>Download</a>'
                        + '<button class=\"btn ghost\" data-copy-url=\"' + esc(url) + '\">Copy link</button>'
                        + '</span></li>';
                }}).join('');
            }} catch (e) {{}}
        }}
        loadRecent();

        // Drag & Drop File Upload
        dropzone.addEventListener('click', () => fileInput.click());
        dropzone.addEventListener('dragover', (e) => {{
            e.preventDefault();
            dropzone.classList.add('dragover');
        }});
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
        dropzone.addEventListener('drop', (e) => {{
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
        }});
        fileInput.addEventListener('change', () => {{
            if (fileInput.files.length) uploadFiles(fileInput.files);
            fileInput.value = '';
        }});

        async function uploadFiles(fileList) {{
            let pwd = sessionStorage.getItem('admin_secret');
            if (!pwd) {{
                pwd = prompt("Enter admin secret:");
                if (!pwd) return;
                sessionStorage.setItem('admin_secret', pwd);
            }}
            for (const file of fileList) {{
                await uploadOne(file, pwd);
            }}
            loadRecent();
        }}

        async function uploadOne(file, pwd) {{
            const li = document.createElement('li');
            li.innerHTML = '<span class="file-name">⏳ ' + esc(file.name) + '</span><span>Uploading…</span>';
            uploadList.prepend(li);

            const formData = new FormData();
            formData.append('file', file);

            status.textContent = 'Uploading ' + file.name + '…';

            try {{
                const res = await fetch('/admin/upload', {{
                    method: 'POST',
                    headers: {{ 'X-Admin-Secret': pwd }},
                    body: formData
                }});
                const data = await res.json();
                if (res.ok) {{
                    li.innerHTML = '<span class="file-name">✅ ' + esc(data.filename) + '</span>'
                        + '<span class="file-actions">'
                        + '<a class="btn" href="' + esc(data.url) + '" target="_blank" rel="noopener">View ↗</a>'
                        + '<a class="btn ghost" href="' + esc(data.url) + '" download>Download</a>'
                        + '<button class="btn ghost" data-copy-url="' + esc(data.url) + '">Copy link</button>'
                        + '</span>';
                    status.textContent = 'Success! File uploaded and shareable URL ready.';
                    status.style.color = '#10b981';
                }} else {{
                    li.innerHTML = '<span class="file-name">❌ ' + esc(file.name) + '</span><span>' + esc(data.detail || ('HTTP ' + res.status)) + '</span>';
                    status.textContent = 'Error: ' + (data.detail || ('HTTP ' + res.status));
                    status.style.color = '#ef4444';
                    if (res.status === 401) sessionStorage.removeItem('admin_secret');
                }}
            }} catch (e) {{
                li.innerHTML = '<span class="file-name">❌ ' + esc(file.name) + '</span><span>' + esc(e.message) + '</span>';
                status.textContent = 'Upload failed: ' + e.message;
                status.style.color = '#ef4444';
            }}
        }}
    </script>
</body>
</html>
"""
