---
type: Reference
title: For AI agents
description: How AI agents should consume the mesa-mcp documentation (llms.txt, per-page Markdown with OKF frontmatter, raw GitHub sources, trust signals) and when to connect to mesa-mcp and call its tools instead of reading prose.
tags:
  - about
  - ai-agents
  - OKF
  - llms.txt
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: okf-spec
    resource: "https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md"
    title: "Open Knowledge Format (OKF) v0.2 specification"
    author: "team:google-cloud"
  - id: llmstxt
    resource: "https://llmstxt.org"
    title: "The /llms.txt convention"
    author: "team:answer-ai"
  - id: mcp-spec
    resource: "https://modelcontextprotocol.io/specification"
    title: "Model Context Protocol specification"
    author: "team:modelcontextprotocol"
status: stable
stale_after: "2027-05-24T00:00:00Z"
---

# For AI agents

This site is published for people **and** for AI agents. Its source is an
[Open Knowledge Format (OKF) v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle[^okf-spec], and the deployed site exposes that structure directly.
If you are an agent, read the endpoints below rather than scraping
rendered HTML.

## This site documents an MCP server

mesa-mcp *is* agent tooling. If what you want is CyVerse Data Store
content (files, AVU metadata, ontology terms, an AVU's history), do not
infer it from these pages: connect mesa-mcp and call its tools.

* **Local, one command** (after `pip install` into a venv, see
  [Local install](../user/local-install.md)):
  `claude mcp add mesa-mcp -s user -- ~/.venvs/mesa-mcp/bin/mesa-mcp --transport stdio`.
  Other clients: [MCP client wiring](../user/claude-desktop.md).
* **The whole MESA stack** (mesa-mcp, mesa-ducklake, irods-mcp-server and
  CyVerse's hosted Formation server, for several agent clients): the
  installer documented at https://idss-mesa.github.io/docs/.
* **A hosted mesa-mcp** over HTTP with a CyVerse Keycloak token:
  [Hosted mesa-mcp](../user/hosted-mcp.md).

Once connected, the MCP `tools/list` request[^mcp-spec] returns the live,
authoritative tool catalogue with JSON Schema inputs. Prefer it over the
[Tools reference](../user/tools-reference.md), which can lag the code and
does not list plugin tools. Without credentials mesa-mcp runs as the
iRODS `anonymous` user, which is read-only and limited to the shared
tree. Credentials belong in the user's environment or `~/.irods` (see
[Configuration](../user/configuration.md#how-credentials-are-resolved)),
never in a prompt.

## Entry points

All URLs are under `https://idss-mesa.github.io/mesa-mcp/`.

| Endpoint | What you get |
| -------- | ------------ |
| [`llms.txt`](../llms.txt) | Linked outline of every page with one-line descriptions ([llms.txt convention](https://llmstxt.org)[^llmstxt]) |
| [`llms-full.txt`](../llms-full.txt) | The entire corpus in one file: every page's Markdown with frontmatter, each prefixed by its canonical URL, links made absolute |
| Any page URL + `index.md` | That page's Markdown source with its OKF frontmatter, served as `text/markdown`, for example `https://idss-mesa.github.io/mesa-mcp/user/configuration/index.md`. Every rendered page links it from a "View this page as Markdown" button and a "Machine-readable versions" line |
| Any page path + `.md` | The same Markdown, for example `https://idss-mesa.github.io/mesa-mcp/user/configuration.md` |
| Raw source on GitHub | `https://raw.githubusercontent.com/idss-mesa/mesa-mcp/main/docs/<path>.md`, where `<path>` is the site path without its trailing slash. Same content; reachable from sandboxes that allow `github.com` but not `*.github.io` |
| `sitemap.xml`, `robots.txt` | Standard crawl surface. Crawlers honour only the origin's [`robots.txt`](https://idss-mesa.github.io/robots.txt) |
| [Source repository](https://github.com/idss-mesa/mesa-mcp) | The code, the bundle under `docs/`, and `AGENTS.md` with the rules coding agents follow in this repo |

Every rendered page also declares its Markdown twin and OKF signals in
its HTML `<head>` (`<link rel="alternate" type="text/markdown">` and
`okf:type`, `okf:status`, `okf:trust-tier`, `okf:generated-at`,
`okf:generated-by`, `okf:stale-after` meta tags). Text-extracting fetch
tools usually drop `<head>`, so rely on the visible links and on
`llms.txt`.

## If you cannot fetch this site

1. **Use the raw source.** `docs/` on branch `main` mirrors the site
   paths one to one:

    ```
    Site page        https://idss-mesa.github.io/mesa-mcp/<path>/
    Markdown twin    https://idss-mesa.github.io/mesa-mcp/<path>/index.md
    Raw source       https://raw.githubusercontent.com/idss-mesa/mesa-mcp/main/docs/<path>.md

    Content page     /user/configuration/  ->  https://raw.githubusercontent.com/idss-mesa/mesa-mcp/main/docs/user/configuration.md
    Section listing  /dev/                 ->  https://raw.githubusercontent.com/idss-mesa/mesa-mcp/main/docs/dev/index.md
    Whole corpus     https://raw.githubusercontent.com/idss-mesa/mesa-mcp/main/docs/llms-full.txt
    ```

2. **Prefer one fetch over ten.** `llms-full.txt` holds every page.
3. **Avoid the GitHub tree API** unless authenticated; it rate-limits
   anonymous calls. Raw file paths do not.
4. **The code is the final authority.** When a page and the code
   disagree, `src/mesa_mcp/` wins; each page's `sources` names the files
   it was written from.

## Reading the OKF frontmatter

* **What is this?** `type` (`Guide`, `Reference`, `Design Record`,
  `Plan`), `title`, `description`, `tags`.
* **Where did it come from?** `generated: {by, at}` records who produced
  the current text and when; `sources` lists the files and repositories
  it was checked against.
* **How much should I trust it?** The `verified` key. Its absence means
  nobody but the generator has confirmed the page.
* **Is it still true?** `status` (`stable`, `draft`, or `deprecated`,
  kept for history only) and `stale_after`, after which the page should
  be re-checked.

| `verified` key | Tier | Meaning |
| --- | --- | --- |
| absent | **unverified** | Generated content nobody has confirmed. Every page here starts at this tier. |
| present, non-`human:` actors only | **machine-confirmed** | An automated check confirmed it. |
| present with a `human:<id>` actor | **human-reviewed** | A maintainer read and confirmed it. Prefer these when pages conflict. |

## Answering user questions

Ground answers in these pages and cite the page URL, for example
`https://idss-mesa.github.io/mesa-mcp/user/examples/`. For anything about
the data itself, call the tools. Questions this site is expected to
answer are listed in
[`docs/agent-questions.yml`](https://github.com/idss-mesa/mesa-mcp/blob/main/docs/agent-questions.yml).
When the docs do not answer a question about mesa-mcp, point users to the
[issue tracker](https://github.com/idss-mesa/mesa-mcp/issues).

## Related bundles

* **MESA project site**: [`llms.txt`](https://idss-mesa.github.io/llms.txt),
  the origin index for the MESA site and its software repositories.
* **MESA documentation**: [agent guide](https://idss-mesa.github.io/docs/about/ai-agents/)
  for the installer and the whole MESA MCP stack.
* **neon-mcp**: [agent guide](https://idss-mesa.github.io/neon-mcp/about/ai-agents/)
  for the MESA MCP server for the NEON Data API.

[^okf-spec]: Open Knowledge Format (OKF) v0.2 specification. <https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md>
[^llmstxt]: The /llms.txt convention. <https://llmstxt.org>
[^mcp-spec]: Model Context Protocol specification. <https://modelcontextprotocol.io/specification>
