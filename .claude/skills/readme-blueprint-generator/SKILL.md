---
name: readme-blueprint-generator
description: Use when the user asks for a polished, eye-catching GitHub README for a software project. Project-local fork specialized for visually striking READMEs in the style of github.com/ConardLi/easy-dataset and github.com/HKUDS/CLI-Anything — centered hero, banner image, colorful shields, emoji section headers, News timeline, demo GIF placeholder.
---

# README Blueprint Generator (visual-impact fork)

Goal: produce a `README.md` that **stops the scroll in 2 seconds** and **earns a star in 30 seconds**, while staying technically truthful.

This fork is tuned to match the visual language of high-traffic agent / dev-tool repos. Reference exemplars:

- https://github.com/ConardLi/easy-dataset — centered hero, banner PNG, shield wall, dated News, feature grid with emoji
- https://github.com/HKUDS/CLI-Anything — `<h1 align="center">` with icon, tagline on two lines, for-the-badge shield row, "Why X" section, expandable News `<details>`

## Sources (in priority order)

1. `CLAUDE.md` — authoritative on architecture, commands, intent
2. `pyproject.toml` / `package.json` / `Cargo.toml` — name, version, license, deps
3. `LICENSE` — SPDX
4. `src/` tree — confirm subcommands and modules actually exist
5. Existing `README.md` — preserve good wording, do not regress
6. Sibling repos referenced from CLAUDE.md (cross-link them)
7. `assets/` directory — if logo / banner / diagram SVGs exist, USE them; if not, CREATE them as part of the task

**Iron rule:** never invent a feature, command, badge, link, version number, contributor count, or screenshot path that isn't backed by one of the above. Empty graphs and 404 image links are worse than no image at all.

## Required structure (visual-impact layout)

```
1.  Centered hero block
    - <div align="center"> ... </div>
    - Logo or banner (SVG/PNG from assets/)
    - H1 with project name (or image-as-h1)
    - Bold one-liner tagline (≤ 14 words)
    - Two-line poetic subtitle if it fits the project's voice
    - Shield wall: 4–8 badges in `style=for-the-badge` for the headline metrics,
      then a row of `style=flat` badges for secondary metrics
    - Language selector if docs/README.<lang>.md exist
    - Section nav: [Features] · [Quick Start] · [Demo] · [Contributing]
2.  Banner / teaser image  (assets/banner.svg or .png) — full-width, centered
3.  News timeline (optional, only if there are real dated events)
    - Most recent 5 items inline, older entries inside <details>
4.  "Why <project>?" — bullet list with bolded leads, each ≤ 1 sentence
5.  Architecture diagram — SVG centered, with caption
6.  Quick Start — copy-pasteable, ≤ 12 lines, must work end-to-end
7.  Demo — embedded GIF/MP4 (assets/demo.gif) OR a placeholder block
    that says exactly which scenario to record
8.  Features at a glance — emoji-led bullet grid OR feature table
9.  Commands / API surface — table with `command | what | analogy`
10. Comparison ("Why not X?") — only with a real incumbent
11. Supported backends / integrations — table with honest status column
12. Development — clone, install, test, lint
13. Project structure — pruned tree
14. Companion / related projects
15. Contributing / Star History note (only if repo has contributors)
16. License
```

## Hero block recipes

### Recipe A — image-as-h1 (CLI-Anything style)

```markdown
<h1 align="center">
  <img src="assets/logo.svg" alt="" width="72" style="vertical-align: middle;">
  &nbsp;<project-name>: <punchy-tagline>
</h1>

<p align="center">
  <strong>Line one of the poetic subtitle.<br>
  Line two that lands the value prop.</strong>
</p>
```

### Recipe B — banner-then-h1 (easy-dataset style)

```markdown
<div align="center">

<img src="assets/banner.svg" alt="<project> banner" width="820">

# <project-name>

**One-line tagline that fits in the social card preview**

</div>
```

### Shield wall template

```markdown
<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-2_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-yellow?style=for-the-badge" alt="License"></a>
  <a href="#supported-solvers"><img src="https://img.shields.io/badge/Solvers-7_backends-green?style=for-the-badge" alt="Solvers"></a>
  <a href="https://github.com/svd-ai-lab/sim-skills"><img src="https://img.shields.io/badge/Agent_Skills-sim--skills-8A2BE2?style=for-the-badge" alt="Skills"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10--3.12-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/CLI-Click-green?logo=click&logoColor=white" alt="Click">
  <img src="https://img.shields.io/badge/server-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status">
</p>
```

## Asset generation

**If `assets/` is empty, create it as part of the task. Do not leave broken image links.**

You can author the following without any external image-generation API:

| Asset | Tool | Notes |
|---|---|---|
| `assets/logo.svg` | hand-write SVG | Geometric, monochrome or 2-color. Width ~96 px. |
| `assets/banner.svg` | hand-write SVG | Width ~820 px. Project name + tagline + subtle motif. |
| `assets/architecture.svg` | hand-write SVG | Boxes + arrows. Beats ASCII for the README, but keep ASCII inline as fallback for terminals. |
| `assets/demo.gif` | leave placeholder | Real terminal recording (vhs / asciinema). Document the exact command sequence the user should record. |

**SVG style guidelines:**
- Use the project's monochrome or 2-color palette consistently
- No raster images embedded inside SVG (keep them text-only and grep-able)
- Always set `viewBox` so they scale on GitHub
- Add `<title>` for accessibility

## Style rules

- **Emoji ARE allowed in section headers in this fork** (one per header max), to match the reference exemplars. But: never decorative — each emoji must clearly belong to its section's topic.
- **Tables beat prose.** "What / why / how" → table.
- **Active voice, present tense.** "sim launches solvers" not "solvers can be launched".
- **No marketing fluff.** Banned words: "seamless", "robust", "cutting-edge", "revolutionary", "powerful", "blazing fast" (unless backed by a number).
- **Numbers earn trust.** Driver count, supported versions, test count — pull real numbers from sources.
- **Code blocks are mentally tested.** Every shell snippet runs as written from a clean clone.
- **Link, don't duplicate.** CLAUDE.md and sub-repo READMEs get linked.
- **Centered hero, left-aligned body.** Don't center the whole document.

## Process

1. **Read sources** in priority order. Stop when every required section can be filled without guessing.
2. **Audit `assets/`.** If missing, draft the SVGs needed for hero + architecture and write them under `assets/`.
3. **Draft section by section.**
4. **Self-review against the checklist below.**
5. **Write README.md** with the Write tool, replacing the existing file.
6. **Report** what changed and (importantly) what assets the user still needs to provide (e.g. demo.gif recording).

## Self-review checklist (must pass before writing)

- [ ] Centered hero block with image + tagline + shield wall
- [ ] At least one real SVG asset committed under `assets/`
- [ ] No image link points to a file that doesn't exist
- [ ] Quick Start ≤ 12 lines, runnable from clean clone
- [ ] Every command verified against `cli.py` (or equivalent)
- [ ] Every backend in the support table exists in the driver registry
- [ ] No banned marketing words
- [ ] No invented contributor counts, star counts, or "as featured in" badges
- [ ] News section has real dates or is omitted (no fake dates)
- [ ] Demo section has a real GIF or an explicit "to-record" placeholder block
- [ ] Length ≤ 350 lines

## Anti-patterns

| Don't | Why |
|---|---|
| Reference `./assets/foo.png` without creating it | Broken image kills credibility worse than no image |
| Use `style=for-the-badge` for >8 badges in the headline row | Visual noise; reserve it for the top metrics |
| Claim "1,000+ stars" / "trusted by N teams" without data | Easily falsifiable, immediate trust collapse |
| Add a Trendshift / ProductHunt badge to a brand-new repo | Empty referral = obvious padding |
| Paste full architecture text from CLAUDE.md | Link CLAUDE.md instead |
| Promise "coming soon" features with no date | Roadmap noise |
| List every CLI flag | Belongs in `--help` |
