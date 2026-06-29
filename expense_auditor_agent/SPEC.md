# expense_auditor_agent SPEC

## 1. Overview

A standalone LangGraph-based AI agent that watches a folder for receipt images/PDFs, uses Groq's vision model to extract expense fields, validates and normalises the data, then writes approved entries directly into Spendly's SQLite database after human confirmation.

---

## 2. Tech Stack

| Concern | Choice |
|---|---|
| Workflow engine | LangGraph `StateGraph` |
| LLM | Groq — `ChatGroq` from `langchain-groq` |
| Vision model | `llama-3.2-11b-vision-preview` (Groq) |
| Image processing | Pillow |
| State schema | Pydantic `AgentState` + `ExtractedData` |
| Database | SQLite via parent project's `database.db` (`create_expense`, `get_db`) |
| Configuration | `.env` file via `python-dotenv` |

---

## 3. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | — | Groq API key. Get free at console.groq.com/keys |
| `GROQ_MODEL` | No | `llama-3.2-11b-vision-preview` | Groq model for vision + JSON extraction |
| `AUDITOR_POLL_INTERVAL` | No | `5` | Seconds between folder polls |

---

## 4. Pydantic State Schema

```python
AgentState
  file_path:        Optional[str]        # absolute path to receipt file
  file_name:        Optional[str]        # display name
  raw_image_base64: Optional[str]       # PNG-encoded image data
  extracted_data:  Optional[ExtractedData]
  status:           ProcessingStatus    # PENDING | EXTRACTED | APPROVED | REJECTED | SAVED | ERROR
  approved:         bool                # human approval flag
  user_id:          int                 # Spendly user id (default 1 = demo user)
  error_message:    Optional[str]

ExtractedData
  amount:      Optional[float]
  category:    Optional[str]
  date:        Optional[str]   # YYYY-MM-DD
  description: Optional[str]
```

---

## 5. Spendly Valid Categories

```
Food, Transport, Bills, Health, Entertainment, Shopping, Other
```

Any model-returned category must be normalised against this list (case-insensitive substring match → fallback `Other`).

---

## 6. LangGraph Nodes

| Node | Responsibility |
|---|---|
| `extract_receipt` | Load image with Pillow → base64 PNG → send to Groq vision model → parse JSON response → return `ExtractedData` |
| `validate_data` | Normalise category against 7 valid categories; set `status = EXTRACTED` |
| `human_approval` | Block graph, print extracted data to terminal, prompt for `y`/`n`, set `status = APPROVED` or `REJECTED` |
| `save_to_db` | If `approved == True`: call `create_expense()` from `database.db` → return `SAVED`. If `False`: return `REJECTED` |
| `error_handler` | Log error message; always return `ERROR` status |

---

## 7. Graph Edges

```
Entry
  |
  v
extract_receipt --> validate_data --> human_approval --> save_to_db --> END
                             |                |
                             v                v
                      error_handler         END
                             |                |
                             v                v
                             END              END
```

### Conditional routing functions

- `route_after_validate`: ERROR → `error_handler`, else → `human_approval`
- `route_after_approval`: `approved == True` → `save_to_db`, else → END
- `route_after_save`: → END

---

## 8. Polling Loop (run)

```
- Poll incoming_receipts/ every AUDITOR_POLL_INTERVAL seconds
- Skip files with .processed suffix
- For each new file: invoke graph with AgentState(file_path=..., user_id=<resolved uid>)
- After processing (approved, rejected, or error): rename file to <filename>.processed
- Continue polling until KeyboardInterrupt
```

### User resolution (auto)

```
1. Try demo@spendly.com (id=1)
2. Fall back to first user in DB
3. Abort if no users exist
```

---

## 9. Supported Input Formats

`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.pdf`

PDFs are rendered to a PNG via Pillow before encoding.

---

## 10. Output

Approved expenses are inserted into `spendly.db` → `expenses` table via `create_expense()`:

```python
create_expense(user_id, amount, category, date, description)
```

---

## 11. Error Handling

| Failure | Action |
|---|---|
| Image load failure | Set ERROR status, rename to `.processed`, continue |
| LLM call failure / non-JSON response | Set ERROR, rename to `.processed`, continue |
| Invalid amount (None or ≤ 0) | Set ERROR in `save_to_db`, skip insert |
| No users in DB | Abort before entering polling loop |

---

## 12. File Structure

```
expense_auditor_agent/
├── agent_loop.py           # Main script (LangGraph + polling loop)
├── requirements.txt         # pip install -r requirements.txt
├── .env                     # GROQ_API_KEY, optional GROQ_MODEL
├── SPEC.md                 # This file
└── incoming_receipts/      # Drop receipt images/PDFs here
```

---

## 13. To Run

```bash
# Set API key (if not using .env)
export GROQ_API_KEY=gsk_...

python expense_auditor_agent/agent_loop.py
```

---

*Last updated: 2026-06-29*