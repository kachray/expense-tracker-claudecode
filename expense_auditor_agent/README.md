# Spendly Receipt Auditor Agent

A standalone agent that watches a folder for receipt images/PDFs, uses a
miniMax/m2.7 vision model via an NVIDIA NIM proxy to extract expense
fields, and writes the data directly into the Spendly SQLite database
after human confirmation.

---

## Directory layout

```
expense_auditor_agent/
├── agent_loop.py           # Main polling + vision + human-review loop
├── requirements.txt        # pip install -r requirements.txt
├── README.md               # This file
└── incoming_receipts/      # Drop receipt images/PDFs here
```

---

## Quick start

### 1 — Install dependencies

```bash
pip install -r expense_auditor_agent/requirements.txt
```

> Pillow is used to render PDF pages into images for the vision API.
> The agent also needs access to the parent project's `database.db`,
> so make sure Spendly's own `requirements.txt` has been installed.

### 2 — Set environment variables

```bash
# --------------------------------------------------- #
# Linux / macOS                                       #
# --------------------------------------------------- #
# Point at your local NIM/CLaMA-instance proxy
export NIM_BASE_URL="http://localhost:8080/v1"        # ← adjust to your proxy
export NIM_API_KEY="not-needed-for-local-proxies"   # optional

# Override model name if your proxy uses a different identifier
export NIM_MODEL="minimaxi/minimax-2.7-flash"       # optional, default shown

# How often to scan incoming_receipts/ (seconds)
export AUDITOR_POLL_INTERVAL="5"                    # optional, default 5s
```

```powershell
# --------------------------------------------------- #
# Windows PowerShell                                  #
# --------------------------------------------------- #
$env:NIM_BASE_URL = "http://localhost:8080/v1"      # ← adjust to your proxy
$env:NIM_API_KEY = "not-needed-for-local-proxies"   # optional
$env:NIM_MODEL = "minimaxi/minimax-2.7-flash"       # optional
$env:AUDITOR_POLL_INTERVAL = "5"                    # optional
```

> **NVIDIA NIM users:** if you are connecting to
> `https://integrate.api.nvidia.com/v1` (the public NIM gateway), set
> `NIM_API_KEY` to your NVIDIA API key.  For local proxies (e.g. a
> local inference server) the key is usually not required.

### 3 — Run the agent

```bash
python expense_auditor_agent/agent_loop.py
```

### 4 — Drop receipts in

Drop `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, or `.pdf` files into
`expense_auditor_agent/incoming_receipts/`.  The agent will pick them up
on the next poll cycle and prompt you in the terminal before writing
anything to the database.

---

## How it works

1. **Polling** — every `AUDITOR_POLL_INTERVAL` seconds the script scans
   `incoming_receipts/` for new image or PDF files it hasn't processed yet.
2. **Image loading** — each file is loaded with Pillow.  PDFs are rendered
   to an RGB image (first page).  All images are re-encoded as base64
   PNG/JPEG data URLs: `data:image/png;base64,...`
3. **Vision extraction** — the data URL is sent to the NIM endpoint
   (`POST $NIM_BASE_URL/chat/completions`) using the standard OpenAI SDK
   `image_url` content block.  The model is asked to return raw JSON with
   `{amount, category, date, description}`.
4. **Category validation** — the returned category is matched (case-insensitively)
   against Spendly's 7 valid categories: `Food`, `Transport`, `Bills`,
   `Health`, `Entertainment`, `Shopping`, `Other`.  Unrecognised values
   fall back to `Other`.
5. **Human in the loop** — the extracted data is printed to the terminal:

   ```
   =====================================================
     EXTRACTED RECEIPT DATA
   =====================================================
     Amount:      149.99
     Category:    Food
     Date:        2026-06-27
     Description: Whole Foods Market groceries
   =====================================================

   Do you want to log this expense? (y/n):
   ```

   - `y` → calls `create_expense()` from `database.db` and moves the
     file to `receipt.pdf.processed`.
   - `n` → skips the insert and also moves the file to `.processed`.
   - Any other key → re-prompts.

6. **User assignment** — expenses are always logged under the `demo@spendly.com`
   seeded user (id 1).  If that user is deleted the script finds the
   first user in the database as a fallback.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `NIM_BASE_URL` | `https://integrate.api.nvidia.com/v1` | Base URL of your NIM-compatible proxy |
| `NIM_API_KEY` | `not-supplied` | API key for the proxy (often unused for local proxies) |
| `NIM_MODEL` | `minimaxi/minimax-2.7-flash` | Model identifier on the proxy |
| `AUDITOR_POLL_INTERVAL` | `5` | Seconds between folder polls |

---

## Stopping the agent

`Ctrl-C` exits cleanly.  Resume later — already-processed files are
renamed to `*.processed` and will not be re-submitted to the vision API.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `openai not found` | `pip install -r expense_auditor_agent/requirements.txt` |
| `Pillow not found` | `pip install pillow` |
| `Could not open PDF` | Verify the file is a valid PDF; some scanned PDFs may need OCR pre-processing |
| Vision model returns invalid JSON | The receipt may be blurry — rename/move and re-drop the file to retry |
| Model returns a category not in the 7 allowed | Script normalises it and defaults to `Other` silently |
| No users in database | First create a user by registering in the Spendly web app |
| Connection refused to NIM proxy | Check `NIM_BASE_URL` is reachable; verify your proxy is running |