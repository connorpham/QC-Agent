# Plan 0 — Spikes: Agent SDK and Storage Platforms

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer, with measurements, the questions the spec marks "verify in spike" before the agent and storage layers are built.

**Architecture:** Throwaway scripts under `spikes/` (git-ignored except the results file). Nothing here is product code; results are recorded in `docs/superpowers/spikes/2026-10-spike-results.md` and feed Plans 2 and 4.

**Tech Stack:** Python 3.12 via uv, `claude-agent-sdk`, `msal`, `httpx`, `google-api-python-client`, `google-auth`.

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` sections 7.3, 8.2, 8.3, 15.

## Global Constraints

- No customer data. Use only the synthetic documents created in Task 1.
- Secrets only in `spikes/.env` (git-ignored). Never paste keys into scripts, logs or the results file.
- Agent budget per spike session: `max_budget_usd=0.50`.
- Model: `claude-opus-5`.

## Review Focus

- A built-in tool (Read, Bash, Write) still offered to the agent despite `disallowed_tools` → the results must list the exact tool names from the `init` system message, not assume.
- Session transcripts written to `~/.claude/projects/` instead of the relocated `CLAUDE_CONFIG_DIR` → check both locations after the run.
- Two concurrent sessions interfering (shared state, crashes, mixed tool results) → each session's proposals must reference only its own document ids.
- SharePoint overwrite not creating a new version (library versioning disabled) → record the library's versioning setting.
- Google Drive revisions auto-pruned → confirm `keepForever` is accepted on the revision.

---

### Task 1: Spike workspace and synthetic documents

**Files:**
- Create: `spikes/pyproject.toml`, `spikes/.env.example`, `spikes/make_docs.py`
- Modify: `.gitignore` (root)

- [ ] **Step 1: Ignore spike artefacts**

Append to the root `.gitignore`:

```gitignore
spikes/.env
spikes/.venv/
spikes/out/
spikes/docs/
```

- [ ] **Step 2: Create the spike project**

```bash
mkdir -p spikes && cd spikes
uv init --bare --python 3.12
uv add claude-agent-sdk msal httpx google-api-python-client google-auth python-dotenv
```

`spikes/.env.example`:

```dotenv
ANTHROPIC_API_KEY=
MS_TENANT_ID=
MS_CLIENT_ID=
MS_CLIENT_SECRET=
MS_SITE_HOSTNAME=techvify.sharepoint.com
MS_SITE_PATH=/sites/qc-agent-test
GOOGLE_SERVICE_ACCOUNT_FILE=./service-account.json
GOOGLE_SHARED_DRIVE_ID=
```

Copy to `spikes/.env` and fill in. Add `spikes/service-account.json` to `.gitignore` as well.

- [ ] **Step 3: Generate 10 synthetic Markdown documents**

`spikes/make_docs.py`:

```python
"""Create 10 small synthetic project documents (no customer data)."""
from pathlib import Path

DOCS = {
    "d01": ("Project Charter - Demo Shop", "# Project Charter\n## Objectives\nLaunch an online shop.\n## Stakeholders\nProduct owner, QA lead.\n"),
    "d02": ("Business Requirements", "# Business Requirements Document\n## Business goals\nIncrease online sales by 20%.\n## Scope\nCatalogue, cart, checkout.\n"),
    "d03": ("Software Requirements Specification", "# SRS\n## FR-001 Login\nThe system shall allow login with e-mail and password.\n## NFR-001\nPages load in under 2 s.\n"),
    "d04": ("Đặc tả use case", "# Use case UC-01: Đặt hàng\nTác nhân: Khách hàng\nLuồng chính: chọn sản phẩm, thanh toán.\n"),
    "d05": ("Architecture overview", "# C4 Context\nThe shop talks to a payment gateway and an e-mail service.\n## Containers\nWeb app, API, PostgreSQL.\n"),
    "d06": ("Database design", "# ERD\nTables: customer, order, order_item, product.\norder.customer_id -> customer.id\n"),
    "d07": ("Test plan v1", "# Test Plan\n## Scope\nFunctional and regression testing.\n## Entry criteria\nBuild deployed to staging.\n"),
    "d08": ("Kết quả kiểm thử sprint 3", "# Test report sprint 3\nPassed 120, failed 4, blocked 1.\nDefects: BUG-12, BUG-15.\n"),
    "d09": ("Deployment guide", "# Deployment\n1. Build image\n2. Run migrations\n3. Restart service\n"),
    "d10": ("Meeting notes", "# Weekly sync\nDiscussed timeline; no decisions.\n"),
}

def main() -> None:
    out = Path(__file__).parent / "docs"
    out.mkdir(exist_ok=True)
    for doc_id, (title, body) in DOCS.items():
        (out / f"{doc_id}.md").write_text(f"<!-- title: {title} -->\n{body}", encoding="utf-8")
    print(f"Wrote {len(DOCS)} documents to {out}")

if __name__ == "__main__":
    main()
```

Run: `uv run python make_docs.py` → Expected: `Wrote 10 documents to .../spikes/docs`.

- [ ] **Step 4: Commit**

```bash
git add .gitignore spikes/pyproject.toml spikes/uv.lock spikes/.env.example spikes/make_docs.py
git commit -m "chore(spikes): add spike workspace and synthetic documents"
```

---

### Task 2: Agent SDK spike

**Files:**
- Create: `spikes/agent_spike.py`

Questions answered:
1. With only custom tools allow-listed, `permission_mode="dontAsk"` and `disallowed_tools`, which tools does the `init` message list?
2. Does `CLAUDE_CONFIG_DIR` move session transcripts into the given directory, and does anything still appear under `~/.claude/projects/`?
3. With `setting_sources=[]`, does the `init` message show no user or project settings, skills, plugins or MCP servers other than `qc`? (Record the full `init` data keys and the `mcp_servers` / `tools` values.)
4. Do two sessions run concurrently in one process without interference?
5. Cost, turns, duration for 5 documents per session.

- [ ] **Step 1: Write the spike script**

`spikes/agent_spike.py`:

```python
"""Throwaway spike: Claude Agent SDK isolation, tool restriction, concurrency."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

HERE = Path(__file__).parent
DOC_TYPES = ["project-charter", "brd", "srs", "use-cases", "architecture-c4", "erd",
             "test-plan", "test-report", "deploy-guide", "other"]


def make_tools(doc_ids: list[str], proposals: dict[str, dict[str, Any]]) -> list[Any]:
    docs_dir = HERE / "docs"

    @tool("list_documents", "List the documents to classify with a short preview.", {})
    async def list_documents(args: dict[str, Any]) -> dict[str, Any]:
        items = [{"doc_id": d, "preview": (docs_dir / f"{d}.md").read_text(encoding="utf-8")[:300]}
                 for d in doc_ids]
        return {"content": [{"type": "text", "text": json.dumps(items, ensure_ascii=False)}]}

    @tool("read_document", "Read a document in full.", {"doc_id": str})
    async def read_document(args: dict[str, Any]) -> dict[str, Any]:
        doc_id = args["doc_id"]
        if doc_id not in doc_ids:
            return {"content": [{"type": "text", "text": f"Unknown doc_id {doc_id}"}], "is_error": True}
        return {"content": [{"type": "text", "text": (docs_dir / f"{doc_id}.md").read_text(encoding="utf-8")}]}

    @tool("submit_classification", "Submit the document type for one document.",
          {"doc_id": str, "doc_type": str, "confidence": float, "reasoning": str})
    async def submit_classification(args: dict[str, Any]) -> dict[str, Any]:
        if args["doc_id"] not in doc_ids or args["doc_type"] not in DOC_TYPES:
            return {"content": [{"type": "text", "text": f"Invalid. doc_type must be one of {DOC_TYPES}"}],
                    "is_error": True}
        proposals[args["doc_id"]] = args
        return {"content": [{"type": "text", "text": "accepted"}]}

    return [list_documents, read_document, submit_classification]


async def prompt_stream(text: str):  # streaming input form, required for in-process MCP tools
    yield {"type": "user", "message": {"role": "user", "content": text}}


async def run_session(label: str, doc_ids: list[str]) -> dict[str, Any]:
    config_dir = HERE / "out" / label / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    proposals: dict[str, dict[str, Any]] = {}
    server = create_sdk_mcp_server(name="qc", version="1.0.0", tools=make_tools(doc_ids, proposals))
    options = ClaudeAgentOptions(
        cwd=str(HERE / "out" / label),
        system_prompt=(
            "You classify software project documents. Call list_documents, read what you need, "
            f"then call submit_classification once per document. Valid doc types: {', '.join(DOC_TYPES)}. "
            "You cannot write files."
        ),
        model="claude-opus-5",
        mcp_servers={"qc": server},
        allowed_tools=["mcp__qc__list_documents", "mcp__qc__read_document", "mcp__qc__submit_classification"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
                          "Glob", "Grep", "WebSearch", "WebFetch", "Task", "TodoWrite"],
        permission_mode="dontAsk",
        max_turns=30,
        max_budget_usd=0.50,
        setting_sources=[],
        env={"ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"], "CLAUDE_CONFIG_DIR": str(config_dir)},
    )
    started = time.monotonic()
    init_data: dict[str, Any] | None = None
    tool_calls: list[str] = []
    result: ResultMessage | None = None
    async for message in query(prompt=prompt_stream("Classify all documents."), options=options):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            init_data = message.data
        elif isinstance(message, AssistantMessage):
            tool_calls += [b.name for b in message.content if isinstance(b, ToolUseBlock)]
        elif isinstance(message, ResultMessage):
            result = message
    return {
        "label": label,
        "seconds": round(time.monotonic() - started, 1),
        "init_keys": sorted((init_data or {}).keys()),
        "init_tools": (init_data or {}).get("tools"),
        "init_mcp_servers": (init_data or {}).get("mcp_servers"),
        "tool_calls": tool_calls,
        "proposals": proposals,
        "foreign_ids": sorted(set(proposals) - set(doc_ids)),
        "missing_ids": sorted(set(doc_ids) - set(proposals)),
        "result_subtype": result.subtype if result else None,
        "cost_usd": result.total_cost_usd if result else None,
        "usage": result.usage if result else None,
        "session_id": result.session_id if result else None,
        "session_files": sorted(str(p.relative_to(config_dir)) for p in config_dir.rglob("*.jsonl")),
    }


async def main() -> None:
    load_dotenv(HERE / ".env")
    home_projects = Path.home() / ".claude" / "projects"
    before = set(home_projects.rglob("*.jsonl")) if home_projects.exists() else set()
    mode = sys.argv[1] if len(sys.argv) > 1 else "single"
    if mode == "single":
        results = [await run_session("single", ["d01", "d02", "d03", "d04", "d05"])]
    else:
        results = list(await asyncio.gather(
            run_session("concurrent-a", ["d01", "d02", "d03", "d04", "d05"]),
            run_session("concurrent-b", ["d06", "d07", "d08", "d09", "d10"]),
        ))
    after = set(home_projects.rglob("*.jsonl")) if home_projects.exists() else set()
    report = {"mode": mode, "sessions": results, "new_files_in_home_claude": sorted(map(str, after - before))}
    out = HERE / "out" / f"agent-{mode}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run a single session**

Run: `cd spikes && uv run python agent_spike.py single`
Expected: JSON report; `result_subtype` = `success`; `missing_ids` empty. If the run errors on `query(prompt=...)`, record the exact error and retry with `ClaudeSDKClient` (`async with ClaudeSDKClient(options) as c: await c.query("Classify all documents."); async for m in c.receive_response(): ...`), recording which form works.

- [ ] **Step 3: Run two concurrent sessions**

Run: `uv run python agent_spike.py concurrent`
Expected: both sessions `success`; `foreign_ids` empty in both.

- [ ] **Step 4: Record results**

Create `docs/superpowers/spikes/2026-10-spike-results.md` with a section "Agent SDK" answering questions 1–5 using values from `spikes/out/agent-single.json` and `agent-concurrent.json`: exact `init_tools` list, session file locations, `new_files_in_home_claude`, concurrency outcome, cost/turns/seconds per session, SDK version (`uv pip show claude-agent-sdk`), and the recommended `AGENT_CONCURRENCY` and default budgets for Plan 4.

- [ ] **Step 5: Commit**

```bash
git add spikes/agent_spike.py docs/superpowers/spikes/2026-10-spike-results.md
git commit -m "spike: measure Agent SDK isolation, tools and concurrency"
```

---

### Task 3: SharePoint (Microsoft Graph) spike

**Files:**
- Create: `spikes/sharepoint_spike.py`

Prerequisite (IT): Entra app with application permission `Sites.Selected`, admin consent, and a `write` grant on the test site (`POST /sites/{site-id}/permissions` by an admin). Library versioning enabled.

Questions: app-only token works with `Sites.Selected`; simple upload; upload session for a 6 MB file; overwrite creates a new version; list and download a previous version; throttling headers observed.

- [ ] **Step 1: Write the script**

`spikes/sharepoint_spike.py`:

```python
"""Throwaway spike: SharePoint via Microsoft Graph, app-only, Sites.Selected."""
import json
import os
import secrets
from pathlib import Path

import httpx
import msal
from dotenv import load_dotenv

HERE = Path(__file__).parent
GRAPH = "https://graph.microsoft.com/v1.0"
CHUNK = 5 * 320 * 1024  # multiple of 320 KiB as Graph requires


def token() -> str:
    app = msal.ConfidentialClientApplication(
        os.environ["MS_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{os.environ['MS_TENANT_ID']}",
        client_credential=os.environ["MS_CLIENT_SECRET"],
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise SystemExit(f"Token error: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]


def main() -> None:
    load_dotenv(HERE / ".env")
    report: dict[str, object] = {}
    with httpx.Client(headers={"Authorization": f"Bearer {token()}"}, timeout=60) as c:
        site = c.get(f"{GRAPH}/sites/{os.environ['MS_SITE_HOSTNAME']}:{os.environ['MS_SITE_PATH']}").raise_for_status().json()
        drives = c.get(f"{GRAPH}/sites/{site['id']}/drives").raise_for_status().json()["value"]
        drive_id = drives[0]["id"]
        report["site_id"], report["drive_name"] = site["id"], drives[0]["name"]
        base = f"qc-agent-spike/{secrets.token_hex(4)}"

        small = c.put(f"{GRAPH}/drives/{drive_id}/root:/{base}/02-requirements/srs--demo.md:/content",
                      content=b"# SRS v1\n", headers={"Content-Type": "text/markdown"}).raise_for_status().json()
        report["small_upload_item_id"] = small["id"]

        c.put(f"{GRAPH}/drives/{drive_id}/root:/{base}/02-requirements/srs--demo.md:/content",
              content=b"# SRS v2\n", headers={"Content-Type": "text/markdown"}).raise_for_status()
        versions = c.get(f"{GRAPH}/drives/{drive_id}/items/{small['id']}/versions").raise_for_status().json()["value"]
        report["versions_after_overwrite"] = [v["id"] for v in versions]
        oldest = versions[-1]["id"]
        old = c.get(f"{GRAPH}/drives/{drive_id}/items/{small['id']}/versions/{oldest}/content", follow_redirects=True)
        report["oldest_version_content"] = old.content.decode()

        big = os.urandom(6 * 1024 * 1024)
        session = c.post(f"{GRAPH}/drives/{drive_id}/root:/{base}/05-testing/big.bin:/createUploadSession",
                         json={"item": {"@microsoft.graph.conflictBehavior": "replace"}}).raise_for_status().json()
        with httpx.Client(timeout=120) as raw:  # upload URL is pre-authorised; do not send the bearer token
            for start in range(0, len(big), CHUNK):
                chunk = big[start:start + CHUNK]
                end = start + len(chunk) - 1
                r = raw.put(session["uploadUrl"], content=chunk,
                            headers={"Content-Range": f"bytes {start}-{end}/{len(big)}"})
                r.raise_for_status()
        report["large_upload_status"] = r.status_code
        report["throttle_headers_seen"] = [h for h in ("Retry-After", "RateLimit-Remaining") if h in r.headers]
        report["test_folder"] = base
    out = HERE / "out" / "sharepoint.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run**

Run: `uv run python sharepoint_spike.py`
Expected: `versions_after_overwrite` has ≥ 2 ids; `oldest_version_content` is `# SRS v1`; `large_upload_status` is 200 or 201. A 403 on the site lookup means the `Sites.Selected` grant is missing — record it and ask IT.

- [ ] **Step 3: Record results and clean up**

Add a "SharePoint" section to the results file: token flow, permissions actually needed, version behaviour, upload session behaviour, any errors. Delete the test folder in the SharePoint UI.

- [ ] **Step 4: Commit**

```bash
git add spikes/sharepoint_spike.py docs/superpowers/spikes/2026-10-spike-results.md
git commit -m "spike: verify SharePoint upload and versioning via Graph"
```

---

### Task 4: Google Drive spike

**Files:**
- Create: `spikes/gdrive_spike.py`

Prerequisite (IT): service account JSON key; Drive API enabled; service account added to the test Shared Drive as Content manager.

Questions: service account can create folders and files in the Shared Drive; `files.update` on the same id creates a revision; `keepForever` accepted; old revision downloadable.

- [ ] **Step 1: Write the script**

`spikes/gdrive_spike.py`:

```python
"""Throwaway spike: Google Drive Shared Drive with a service account."""
import io
import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

HERE = Path(__file__).parent
FOLDER_MIME = "application/vnd.google-apps.folder"


def main() -> None:
    load_dotenv(HERE / ".env")
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"], scopes=["https://www.googleapis.com/auth/drive"])
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    drive_id = os.environ["GOOGLE_SHARED_DRIVE_ID"]
    report: dict[str, object] = {}

    root = drive.files().create(body={"name": f"qc-agent-spike-{secrets.token_hex(4)}", "mimeType": FOLDER_MIME,
                                      "parents": [drive_id]}, supportsAllDrives=True, fields="id").execute()
    folder = drive.files().create(body={"name": "02-requirements", "mimeType": FOLDER_MIME, "parents": [root["id"]]},
                                  supportsAllDrives=True, fields="id").execute()
    media_v1 = MediaIoBaseUpload(io.BytesIO(b"# SRS v1\n"), mimetype="text/markdown", resumable=True)
    f = drive.files().create(body={"name": "srs--demo.md", "parents": [folder["id"]]}, media_body=media_v1,
                             supportsAllDrives=True, fields="id,headRevisionId").execute()
    media_v2 = MediaIoBaseUpload(io.BytesIO(b"# SRS v2\n"), mimetype="text/markdown", resumable=True)
    updated = drive.files().update(fileId=f["id"], media_body=media_v2, supportsAllDrives=True,
                                   fields="id,headRevisionId").execute()
    revisions = drive.revisions().list(fileId=f["id"], fields="revisions(id,keepForever,modifiedTime)").execute()["revisions"]
    report["revision_ids"] = [r["id"] for r in revisions]
    kept = drive.revisions().update(fileId=f["id"], revisionId=revisions[0]["id"], body={"keepForever": True},
                                    fields="id,keepForever").execute()
    report["keep_forever_first"] = kept.get("keepForever")
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, drive.revisions().get_media(fileId=f["id"], revisionId=revisions[0]["id"]))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    report["first_revision_content"] = buf.getvalue().decode()
    report["head_changed"] = f["headRevisionId"] != updated["headRevisionId"]
    report["test_folder_id"] = root["id"]
    out = HERE / "out" / "gdrive.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run**

Run: `uv run python gdrive_spike.py`
Expected: `revision_ids` has ≥ 2 entries; `keep_forever_first` true; `first_revision_content` is `# SRS v1`; `head_changed` true.

- [ ] **Step 3: Record results and clean up**

Add a "Google Drive" section to the results file. Delete the test folder in Drive.

- [ ] **Step 4: Commit**

```bash
git add spikes/gdrive_spike.py docs/superpowers/spikes/2026-10-spike-results.md
git commit -m "spike: verify Google Drive revisions with a service account"
```
