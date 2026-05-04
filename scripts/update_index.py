"""Generate the top-level index.html gallery from MANIFESTATIONS.md.

Each row of MANIFESTATIONS.md becomes one card. The card links to the
issue and PR on GitHub, and — if the project's directory has its own
`<dir>/index.html` — to that subpage as the "Live" view.

Triggered by the workflow alongside update_log.py. The output file is
in FORBIDDEN_FILES so Claude can never overwrite it; only this
script can update it.
"""
import json
import os
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

REPO_NAME = os.environ.get("REPOSITORY", "Cooli-Lab/sprout")
LOG = Path("MANIFESTATIONS.md")
INDEX = Path("index.html")

# Match rows: | Date | Architect | Decree | Path | Issue | PR | Files |
ROW_RE = re.compile(
    r"\| (\d{4}-\d{2}-\d{2}) \| \[@(?P<arch>[^\]]+)\]\((?P<arch_url>[^)]+)\) \| "
    r"(?P<decree>[^|]+?) \| `(?P<path>[^`]+)` \| "
    r"\[#(?P<issue>\d+)\]\((?P<issue_url>[^)]+)\) \| "
    r"\[#(?P<pr>\d+)\]\((?P<pr_url>[^)]+)\) \|"
)


def parse_log():
    if not LOG.exists():
        return []
    rows = []
    for m in ROW_RE.finditer(LOG.read_text()):
        d = m.groupdict()
        d["date"] = m.group(1)
        d["decree"] = d["decree"].strip().replace("\\|", "|")
        rows.append(d)
    return rows


def gallery_jsonld(rows):
    """ItemList of Article entries — one per manifestation. AI engines
    treat each row as a citable artifact instead of an opaque link."""
    if not rows:
        return ""
    items = []
    for i, r in enumerate(rows):
        path = r["path"]
        has_live = (Path(path) / "index.html").exists()
        url = (
            f"https://cooli.ai/sprouts/{path}/" if has_live
            else f"https://github.com/{REPO_NAME}/tree/main/{path}"
        )
        items.append({
            "@type": "ListItem",
            "position": i + 1,
            "item": {
                "@type": "Article",
                "headline": r["decree"],
                "url": url,
                "datePublished": r["date"],
                "author": {"@type": "Person", "name": "@" + r["arch"], "url": r["arch_url"]},
                "publisher": {
                    "@type": "Organization",
                    "name": "Cooli AI",
                    "url": "https://cooli.ai/",
                    "logo": "https://cooli.ai/logo.png",
                },
                "isPartOf": {
                    "@type": "Collection",
                    "name": "Sprout — Cooli Lab",
                    "url": "https://cooli.ai/sprouts/",
                },
            },
        })
    ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Sprout manifestations",
        "description": "AI-built projects manifested from human-authored GitHub Issues in the Cooli Lab.",
        "itemListElement": items,
    }
    return '<script type="application/ld+json">' + json.dumps(ld, separators=(",", ":")) + "</script>"


def card_html(r):
    has_live = (Path(r["path"]) / "index.html").exists()
    live_link = (
        f'<a class="primary" href="./{escape(r["path"])}/">Live →</a>'
        if has_live
        else f'<a class="primary" href="https://github.com/{escape(REPO_NAME)}/tree/main/{escape(r["path"])}">View source →</a>'
    )
    return f"""    <article class="card">
      <div class="card-meta">
        <span class="date">{escape(r["date"])}</span>
        <span class="path">{escape(r["path"])}/</span>
      </div>
      <h2>{escape(r["decree"])}</h2>
      <div class="architect">by <a href="{escape(r["arch_url"])}">@{escape(r["arch"])}</a></div>
      <div class="links">
        {live_link}
        <a href="{escape(r["issue_url"])}">Issue #{escape(r["issue"])}</a>
        <a href="{escape(r["pr_url"])}">PR #{escape(r["pr"])}</a>
      </div>
    </article>"""


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌱 Sprout — Cooli Lab</title>
<meta name="description" content="Things humans asked for. Things AI built. A public AI-driven sandbox under Cooli Lab.">
<link rel="icon" type="image/png" href="./logo.png">
<meta property="og:title" content="🌱 Sprout — Cooli Lab">
<meta property="og:description" content="Things humans asked for. Things AI built.">
<meta property="og:image" content="https://cooli.ai/logo.png">
<meta name="theme-color" content="#0a0a0f">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#0a0a0f; --darker:#050508; --light:#fff; --gray:#a1a1aa;
  --primary:#00d4ff; --secondary:#7c3aed; --accent:#f472b6;
}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{
  font-family:'Inter',-apple-system,sans-serif;
  background:var(--darker); color:var(--light); line-height:1.6;
  min-height:100vh; padding:3rem 5%;
}}
body::before{{
  content:''; position:fixed; inset:0; z-index:-1;
  background:
    radial-gradient(ellipse at 20% 20%, rgba(124,58,237,.12) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(0,212,255,.08) 0%, transparent 50%);
}}
.parent-link{{display:inline-flex; align-items:center; gap:.45rem; font-family:'Space Grotesk',sans-serif; font-size:.85rem; font-weight:500; color:var(--gray); text-decoration:none; margin:0 0 1.5rem; padding:.4rem .7rem; border-radius:50px; border:1px solid rgba(255,255,255,.08); background:rgba(255,255,255,.02); transition:all .2s ease}}
.parent-link img{{width:22px; height:22px; display:block}}
.parent-arrow{{font-size:.95rem; line-height:1; transition:transform .2s ease}}
.parent-link:hover .parent-arrow{{transform:translateX(-2px)}}
.parent-link:hover{{color:var(--light); border-color:rgba(255,255,255,.18); background:rgba(255,255,255,.05)}}
.parent-wrap{{max-width:1100px; margin:0 auto; padding-bottom:.5rem}}
header{{max-width:1100px; margin:0 auto 3rem; text-align:center}}
header h1{{
  font-family:'Space Grotesk',sans-serif;
  font-size:clamp(2.5rem,6vw,4rem); font-weight:700; letter-spacing:-.02em;
  background:linear-gradient(135deg,var(--primary),var(--secondary));
  -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
}}
header .tagline{{color:var(--gray); font-size:1.05rem; margin-top:.6rem}}
header nav{{margin-top:1.6rem; display:flex; gap:1rem; justify-content:center; flex-wrap:wrap}}
header nav a{{
  font-family:'Space Grotesk',sans-serif; font-size:.88rem; font-weight:500;
  color:var(--gray); text-decoration:none;
  padding:.45rem .9rem; border-radius:50px;
  border:1px solid rgba(255,255,255,.08);
  transition:all .2s ease;
}}
header nav a:hover{{color:var(--light); border-color:rgba(255,255,255,.2); background:rgba(255,255,255,.03)}}
header nav a.cta{{
  color:var(--light);
  background:linear-gradient(135deg,var(--primary),var(--secondary));
  border-color:transparent;
}}
header nav a.cta:hover{{transform:translateY(-1px); box-shadow:0 8px 24px rgba(0,212,255,.25)}}
main{{max-width:1100px; margin:0 auto}}
.gallery{{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(290px,1fr));
  gap:1.25rem;
}}
.card{{
  background:rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.07);
  border-radius:16px; padding:1.5rem;
  display:flex; flex-direction:column; gap:.6rem;
  transition:all .25s ease;
}}
.card:hover{{
  transform:translateY(-3px);
  border-color:rgba(124,58,237,.4);
  background:rgba(255,255,255,.05);
}}
.card-meta{{display:flex; justify-content:space-between; align-items:baseline; font-size:.72rem; letter-spacing:.04em; text-transform:uppercase; color:var(--gray)}}
.card-meta .path{{font-family:'Space Grotesk',monospace; color:rgba(0,212,255,.7); text-transform:none; letter-spacing:0}}
.card h2{{font-family:'Space Grotesk',sans-serif; font-size:1.1rem; font-weight:600; line-height:1.35; letter-spacing:-.01em}}
.card .architect{{font-size:.85rem; color:var(--gray)}}
.card .architect a{{color:var(--gray); text-decoration:none; border-bottom:1px solid rgba(255,255,255,.15)}}
.card .architect a:hover{{color:var(--light); border-bottom-color:rgba(255,255,255,.4)}}
.card .links{{display:flex; gap:.45rem; flex-wrap:wrap; margin-top:auto; padding-top:.6rem}}
.card .links a{{
  font-family:'Space Grotesk',sans-serif;
  font-size:.78rem; font-weight:500; text-decoration:none;
  color:var(--gray);
  padding:.32rem .65rem; border-radius:6px;
  background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.07);
  transition:all .2s ease;
}}
.card .links a:hover{{color:var(--light); background:rgba(255,255,255,.07); border-color:rgba(255,255,255,.15)}}
.card .links a.primary{{
  color:var(--light);
  background:linear-gradient(135deg, rgba(0,212,255,.18), rgba(124,58,237,.18));
  border-color:rgba(0,212,255,.3);
}}
.card .links a.primary:hover{{
  background:linear-gradient(135deg, rgba(0,212,255,.28), rgba(124,58,237,.28));
  border-color:rgba(0,212,255,.5);
}}
.empty{{
  text-align:center; padding:5rem 2rem; color:var(--gray); font-size:1rem;
  border:1px dashed rgba(255,255,255,.08); border-radius:16px;
}}
.empty a{{color:var(--primary); text-decoration:none}}
.intro{{
  max-width:1100px; margin:0 auto 2.5rem;
  padding:1.8rem 1.9rem; border-radius:18px;
  background:linear-gradient(135deg, rgba(0,212,255,.06), rgba(124,58,237,.06));
  border:1px solid rgba(124,58,237,.22);
}}
.intro h2{{font-family:'Space Grotesk',sans-serif; font-size:1.15rem; font-weight:600; margin-bottom:.55rem}}
.intro p{{color:var(--gray); font-size:.95rem; max-width:760px; margin-bottom:1.2rem}}
.intro p strong{{color:var(--light); font-weight:500}}
.steps{{display:grid; grid-template-columns:repeat(3, 1fr); gap:.85rem; margin-bottom:1.4rem}}
.step{{
  background:rgba(255,255,255,.025); border:1px solid rgba(255,255,255,.06);
  border-radius:12px; padding:1rem 1.1rem;
}}
.step-num{{
  display:inline-flex; align-items:center; justify-content:center;
  width:22px; height:22px; border-radius:50%;
  background:linear-gradient(135deg, var(--primary), var(--secondary));
  color:#fff; font-family:'Space Grotesk',sans-serif; font-size:.78rem;
  font-weight:600; margin-bottom:.55rem;
}}
.step-text{{font-size:.85rem; color:var(--gray); line-height:1.55}}
.step-text strong{{color:var(--light); font-weight:500}}
.intro-cta{{display:flex; gap:.6rem; flex-wrap:wrap; align-items:center}}
.intro-cta .primary{{
  display:inline-block;
  font-family:'Space Grotesk',sans-serif; font-size:.92rem; font-weight:500;
  padding:.7rem 1.3rem; border-radius:10px; text-decoration:none;
  color:#fff;
  background:linear-gradient(135deg, var(--primary), var(--secondary));
  transition:transform .2s ease;
}}
.intro-cta .primary:hover{{transform:translateY(-1px)}}
.intro-cta .secondary{{
  font-family:'Space Grotesk',sans-serif; font-size:.85rem; font-weight:500;
  color:var(--gray); text-decoration:none;
  padding:.65rem 1rem; border-radius:10px;
  border:1px solid rgba(255,255,255,.08);
}}
.intro-cta .secondary:hover{{color:var(--light); border-color:rgba(255,255,255,.18)}}
@media (prefers-color-scheme: light){{
  :root{{
    --bg:#fafafa; --darker:#fafafa; --light:#0a0a0f; --gray:#52525b;
    color-scheme:light;
  }}
  body::before{{
    background:
      radial-gradient(ellipse at 20% 20%, rgba(124,58,237,.07) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 80%, rgba(0,212,255,.05) 0%, transparent 50%);
  }}
  .intro, .step, .card{{
    background:rgba(255,255,255,.7); border-color:rgba(15,18,28,.07);
  }}
  .empty{{border-color:rgba(15,18,28,.1)}}
  .parent-link{{background:rgba(15,18,28,.04); border-color:rgba(15,18,28,.08)}}
  .card-meta{{color:#52525b}}
  header nav a{{border-color:rgba(15,18,28,.08)}}
  header nav a:hover{{border-color:rgba(15,18,28,.18); background:rgba(15,18,28,.04)}}
  footer{{border-top-color:rgba(15,18,28,.06)}}
  footer a{{border-bottom-color:rgba(15,18,28,.15)}}
}}
@media (max-width:760px){{
  .steps{{grid-template-columns:1fr}}
}}
footer{{
  max-width:1100px; margin:3rem auto 0;
  text-align:center; color:var(--gray); font-size:.82rem;
  padding-top:2rem; border-top:1px solid rgba(255,255,255,.05);
}}
footer a{{color:var(--gray); border-bottom:1px solid rgba(255,255,255,.12)}}
footer a:hover{{color:var(--light)}}
@media (max-width:540px){{
  body{{padding:2rem 1rem}}
  .gallery{{grid-template-columns:1fr}}
}}
</style>
</head>
<body>
<div class="parent-wrap">
  <a class="parent-link" href="https://cooli.ai/#lab" aria-label="Back to Cooli Lab"><span class="parent-arrow" aria-hidden="true">←</span><img src="./logo.png" alt="">Cooli Lab</a>
</div>
<header>
  <h1>🌱 Sprout</h1>
  <p class="tagline">Things humans asked for. Things AI built.</p>
  <nav>
    <a class="cta" href="https://github.com/{repo}/issues/new/choose">Speak into the void</a>
    <a href="https://github.com/{repo}">Source</a>
    <a href="https://github.com/{repo}/blob/main/MANIFESTATIONS.md">Full log</a>
    <a href="https://cooli.ai">cooli.ai</a>
  </nav>
</header>
<main>
<section class="intro">
  <h2>What is this?</h2>
  <p>Sprout is a public sandbox where <strong>humans speak and AI builds</strong>. Open a GitHub Issue describing what you want — anything benign, in scope, and well-defined — and an autonomous Claude agent reads it, judges it, writes the files, and opens a PR. If it passes the rules, it gets merged and shows up below as a live page.</p>
  <div class="steps">
    <div class="step">
      <div class="step-num">1</div>
      <div class="step-text"><strong>Open an Issue.</strong> Describe what you want built. Be concrete: "a small Markdown-to-slides converter that…"</div>
    </div>
    <div class="step">
      <div class="step-num">2</div>
      <div class="step-text"><strong>The agent judges &amp; builds.</strong> It either roasts the request and walks away, or writes a runnable project + showcase page.</div>
    </div>
    <div class="step">
      <div class="step-num">3</div>
      <div class="step-text"><strong>Auto-merge &amp; publish.</strong> If the laws hold, it merges to main and the result lives at <code style="color:var(--primary)">cooli.ai/sprouts/&lt;name&gt;/</code></div>
    </div>
  </div>
  <div class="intro-cta">
    <a class="primary" href="https://github.com/{repo}/issues/new/choose">Open an issue →</a>
    <a class="secondary" href="https://github.com/{repo}/blob/main/CLAUDE.md">Read the laws</a>
    <a class="secondary" href="https://github.com/{repo}/blob/main/README.md">How it works</a>
  </div>
</section>
{body}
</main>
<footer>
  Three creations per architect. The void has rules. ·
  <a href="https://github.com/{repo}/blob/main/CLAUDE.md">Laws of Creation</a> ·
  <a href="https://github.com/Cooli-Lab/mulch">Mulch (sister)</a>
</footer>
</body>
</html>
"""


def main():
    rows = parse_log()
    if not rows:
        body = '<div class="empty">Nothing manifested yet. <a href="https://github.com/{repo}/issues/new/choose">Be the first</a>.</div>'.format(repo=REPO_NAME)
    else:
        body = '<div class="gallery">\n' + "\n".join(card_html(r) for r in rows) + "\n  </div>"
    body = gallery_jsonld(rows) + body
    INDEX.write_text(PAGE.format(repo=REPO_NAME, body=body))
    print(f"Wrote {INDEX} with {len(rows)} card(s).")


if __name__ == "__main__":
    main()
