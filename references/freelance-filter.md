# Freelance Relevance Filter

This file defines what counts as a **relevant** freelancing opportunity for Parth.
The script `scripts/gmail_freelance_digest.py` reads this file to score incoming
freelancer emails. Edit it freely — no code changes required.

## How scoring works

- Each email is scanned for keywords from the lists below.
- `strong_keywords` hits add **+3** each.
- `soft_keywords` hits add **+1** each.
- `exclude_keywords` hits subtract **-5** each (spam / irrelevant signals).
- Email is sent to Discord + archived if final score >= `threshold` (default 3).

---

## Profile: Parth (CS & Eng, AI & DS)

3rd-year B.Tech CSE (AI & DS). Building side projects (e.g. "vela" personal
assistant). Transitioning to freelancing. Comfortable with Python, ML/DL,
web dev, automation, data work.

### strong_keywords
- python, machine learning, deep learning, ml, dl, nlp, llm, langchain
- rag, computer vision, cv, pytorch, tensorflow, scikit, data science
- data analysis, automation, scraping, selenium, api, rest, fastapi
- flask, django, react, nextjs, typescript, javascript, node, chatbot
- ai agent, openai, fine-tuning, prompt, etl, sql, postgres, mongodb
- freelance, contract, part-time, remote

### soft_keywords
- web, website, dashboard, frontend, backend, fullstack, script, bot
- telegram, discord, whatsapp, excel, csv, report, visualization
- cloud, aws, gcp, docker, git, github, portfolio, student, beginner
- fixed price, hourly, urgent, quick, budget, rate, milestone, proposal, bid

### exclude_keywords
- crypto, nft, forex, gambling, casino, adult, dating, essay, homework
- "write my", onlyfans, loan, bitcoin, trading signal, "get rich"
- survey, sweepstakes, lottery, newsletter, subscribe, unsubscribe
- invitation, "wants to cite you", "make the most of", internship
- intern, "job alert", "hiring alert", webinar, "last chance", sale
- discount, "open for", unstop, "millionaire", "building blocks",
"present your research", conference, summit, "read this", podcast

### downweight_keywords  (-3 each)
Pure video/design/creative gigs that mention a stray "web"/"api" word and
falsely cross the threshold. Subtracts but does NOT hard-block, so hybrid
AI+video projects (which also match strong ML keywords) still get through.
- video editing, after effects, premiere pro, final cut, "motion graphics"
- photoshop, illustrator, graphic design, logo design, "ui/ux", "ui ux"
- "video production", videography, "youtube video", animation, "3d modeling"
- "thumbnail", "social media post", "instagram post", canva, "t-shirt"

---

## Gig-signal requirement (Option B)

A mail is only sent to Discord if it has at least ONE genuine **gig signal**
in addition to skill keywords. This filters out newsletters, LinkedIn
invites, and internship alerts that merely mention "ai/ml/data" but are
not actual freelance projects you can bid on.

If no gig signal is present, the mail is skipped even if skill score is high.

### gig signals
- budget, rate, usd, inr, "rs ", per hour, hourly, fixed price
- "hire you", "hiring for", "project for you", "paid project"
- "looking for a developer", "looking for someone", "need a developer"
- "we'd like to offer", "we are looking for", "can you help us build"
- freelance, contract, upwork, fiverr, "freelancer.com", toptal
- milestone, proposal, bid, outsource, "side project", consulting
- "available for", "reach out"

---

## Sender allowlist (freelancer / job platforms)

Only emails FROM these domains are treated as freelancer mail.
Everything else is ignored (so personal mail is never touched).

- upwork.com
- fiverr.com
- freelancer.com
- linkedin.com  (job alerts / recruiter inmails)
- indeed.com
- toptal.com
- guru.com
- peopleperhour.com
- simplyhired.com
- flexjobs.com
- wellfound.com (angel.co)

To add a platform, append its domain to `sender_domains` in the script
or ask the AIOS to add it here.

---

## Discord delivery

Set `DISCORD_WEBHOOK_URL` in `.env`. The script posts a compact embed:
- Title: job / project subject
- From: sender
- Score + matched keywords
- Snippet of the email body
- A Gmail "view" link

---

## Safety

- Default run is `--dry-run` (no Discord post, no archive).
- Processed message IDs are logged to `scripts/.freelance_digest_cache.json`
  so re-runs never double-post.
- Archive = remove `INBOX` label only. Mail is NEVER deleted.
- Use `--limit N` to cap how many emails are processed per run.
