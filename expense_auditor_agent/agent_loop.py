"""
expense_auditor_agent/agent_loop.py
====================================
LangGraph-based receipt auditor.
Polls incoming_receipts/, extracts expense data via Groq vision model,
previews to human for approval, then commits to Spendly SQLite db.
"""

import os
import sys
import json
import time
import base64
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import groq  # raw groq client -- confirmed free Groq tier compatible

from pydantic import BaseModel, Field

# ------------------------------------------------------------------ #
# Groq client (raw, not langchain-groq -- avoids version conflicts)  #
# ------------------------------------------------------------------ #

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
if not GROQ_API_KEY:
    sys.stderr.write(
        "[ERROR] GROQ_API_KEY not set in .env or environment.\n"
        "  Get a free key at https://console.groq.com/keys\n"
    )
    sys.exit(1)

# ------------------------------------------------------------------ #
# Retry helper                                                        #
# ------------------------------------------------------------------ #

def _groq_with_retry(fn, *args, max_retries=3, **kwargs):
    """
    Call fn(*args, **kwargs) up to max_retries times with exponential
    backoff. Specifically handles groq timeout errors.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except groq.RateLimitError as exc:
            wait = 2 ** attempt
            print(f"[RETRY] Rate limited -- waiting {wait}s before retry {attempt}/{max_retries}")
            time.sleep(wait)
        except groq.APIConnectionError as exc:
            wait = 2 ** attempt
            print(f"[RETRY] Connection error -- waiting {wait}s before retry {attempt}/{max_retries}")
            time.sleep(wait)
        except Exception as exc:
            # Don't retry on unexpected errors -- fail fast
            raise
    raise RuntimeError(f"Groq call failed after {max_retries} retries")


# ------------------------------------------------------------------ #
# Groq client (raw, not langchain-groq -- avoids version conflicts)  #
# ------------------------------------------------------------------ #

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
if not GROQ_API_KEY:
    sys.stderr.write(
        "[ERROR] GROQ_API_KEY not set in .env or environment.\n"
        "  Get a free key at https://console.groq.com/keys\n"
    )
    sys.exit(1)

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.2-11b-vision-preview")
GROQ_TIMEOUT = float(os.environ.get("GROQ_TIMEOUT", "60"))  # seconds
POLL_INTERVAL = float(os.environ.get("AUDITOR_POLL_INTERVAL", "5"))

client = groq.Groq(api_key=GROQ_API_KEY)

# ------------------------------------------------------------------ #
# Spendly DB path                                                    #
# ------------------------------------------------------------------ #

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parent
DB_PATH = _PROJECT_ROOT / "spendly.db"

sys.path.insert(0, str(_PROJECT_ROOT))
from database.db import create_expense, get_db

# ------------------------------------------------------------------ #
# Valid categories (must match app.py VALID_CATEGORIES)             #
# ------------------------------------------------------------------ #

VALID_CATEGORIES = [
    "Food", "Transport", "Bills", "Health",
    "Entertainment", "Shopping", "Other",
]

# ------------------------------------------------------------------ #
# Pydantic state schema                                               #
# ------------------------------------------------------------------ #

from enum import StrEnum

class ProcessingStatus(StrEnum):
    PENDING   = "pending"
    EXTRACTED = "extracted"
    APPROVED  = "approved"
    REJECTED  = "rejected"
    SAVED     = "saved"
    ERROR     = "error"


class ExtractedData(BaseModel):
    amount:      Optional[float] = None
    category:    Optional[str]  = None
    date:        Optional[str]  = None
    description: Optional[str]  = None


class AgentState(BaseModel):
    file_path:        Optional[str]        = None
    raw_image_base64: Optional[str]        = None
    file_name:        Optional[str]        = None
    extracted_data:   Optional[ExtractedData] = None
    status:           ProcessingStatus     = ProcessingStatus.PENDING
    approved:         bool                 = False
    user_id:          int                  = 1
    error_message:    Optional[str]        = None

# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #

def _resolve_user_id() -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
    ).fetchone()
    conn.close()
    if row:
        print(f"[INFO] Logging expenses under user id {row['id']} (demo@spendly.com).")
        return row["id"]
    conn = get_db()
    row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    conn.close()
    if not row:
        sys.stderr.write("[ERROR] No users in Spendly DB. Create one at http://localhost:5001/register\n")
        sys.exit(1)
    print(f"[INFO] Logging expenses under user id {row['id']}.")
    return row["id"]


def _poll_files() -> list[Path]:
    if not INCOMING_DIR.is_dir():
        INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    supported = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}
    files = [
        p for p in INCOMING_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in supported
    ]
    files.sort(key=lambda p: p.stat().st_mtime)
    return files


def _load_image(path: Path) -> str:
    """Load any image/PDF with Pillow, return base64 PNG string."""
    from PIL import Image
    img = Image.open(path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _processed_name(path: Path) -> Path:
    return path.with_name(path.name + ".processed")


def _normalise_category(raw: str) -> str:
    if not raw:
        return "Other"
    for valid in VALID_CATEGORIES:
        if valid.lower() == raw.lower():
            return valid
    for valid in VALID_CATEGORIES:
        if valid.lower() in raw.lower():
            return valid
    print(f"[WARN] Category '{raw}' not recognised -- defaulting to 'Other'.")
    return "Other"


# ------------------------------------------------------------------ #
# LangGraph nodes                                                     #
# ------------------------------------------------------------------ #

def extract_receipt_node(state: AgentState) -> dict:
    """
    Load image, send to Groq vision model with a structured JSON prompt,
    parse and return ExtractedData.
    """
    path = Path(state.file_path) if state.file_path else None
    if not path or not path.exists():
        return {"status": ProcessingStatus.ERROR, "error_message": f"File not found: {state.file_path}"}

    print(f"\n[EXTRACT] Processing: {path.name}")

    try:
        b64 = _load_image(path)
    except Exception as exc:
        return {"status": ProcessingStatus.ERROR, "error_message": f"Image load failed: {exc}"}

    prompt = f"""\
You are a receipt-parsing assistant. Return ONLY valid JSON with these exact fields -- no markdown, no explanation:

{{
  "amount": <float>,
  "category": <one of: {", ".join(VALID_CATEGORIES)}>,
  "date": "<YYYY-MM-DD>",
  "description": "<string or null>"
}}

Rules:
- amount: strip currency symbols/commas, return plain float. Use 0.0 if unreadable.
- category: pick the single best match from the allowed list above.
- date: use the date on the receipt or today's date (2026-06-29) if absent.
- description: summarise merchant/purchase in 80 chars or less, or use null.
- Return ONLY raw JSON.
"""

    today = date.today().isoformat()
    prompt = prompt.replace("2026-06-29", today)

    def _call():
        return client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=512,
            temperature=0.3,
            timeout=GROQ_TIMEOUT,
        )

    try:
        response = _groq_with_retry(_call, max_retries=2)
    except Exception as exc:
        return {"status": ProcessingStatus.ERROR, "error_message": f"Groq API call failed after retries: {exc}"}

    raw = ""
    try:
        raw = response.choices[0].message.content.strip()
    except (AttributeError, IndexError):
        return {"status": ProcessingStatus.ERROR, "error_message": "Empty response from Groq."}

    print(f"[DEBUG] LLM raw response:\n{raw}\n")

    if not raw:
        return {"status": ProcessingStatus.ERROR, "error_message": "LLM returned empty content."}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "status": ProcessingStatus.ERROR,
            "error_message": f"LLM returned invalid JSON: {exc}\nRaw: {raw[:200]}",
        }

    # Normalise amount
    amount_val = data.get("amount")
    if amount_val is None:
        amount = None
    else:
        try:
            amount = float(amount_val)
        except (ValueError, TypeError):
            amount = None

    # Normalise category
    raw_date = data.get("date") or date.today().isoformat()

    extracted = ExtractedData(
        amount=amount,
        category=data.get("category"),
        date=raw_date,
        description=data.get("description"),
    )

    print(
        f"[EXTRACT] amount={extracted.amount}, category={extracted.category}, "
        f"date={extracted.date}, description={extracted.description}"
    )

    return {
        "raw_image_base64": b64,
        "extracted_data": extracted,
        "status": ProcessingStatus.EXTRACTED,
        "error_message": None,
    }


def validate_data_node(state: AgentState) -> dict:
    """Normalise category against Spendly's 7 allowed categories."""
    ed = state.extracted_data
    if ed is None:
        return {"status": ProcessingStatus.ERROR, "error_message": "No extracted data to validate."}

    normalised = _normalise_category(ed.category or "")

    validated = ExtractedData(
        amount=ed.amount,
        category=normalised,
        date=ed.date or date.today().isoformat(),
        description=ed.description,
    )

    print(f"[VALIDATE] '{ed.category}' -> '{normalised}'")

    return {
        "extracted_data": validated,
        "status": ProcessingStatus.EXTRACTED,
    }


def human_approval_node(state: AgentState) -> dict:
    """
    Block and prompt human for y/n approval.
    y -> status = APPROVED, approved = True
    n -> status = REJECTED, approved = False
    """
    data = state.extracted_data
    if data is None:
        return {"status": ProcessingStatus.ERROR, "error_message": "No data to present for approval."}

    print("\n" + "=" * 56)
    print("  EXTRACTED RECEIPT DATA")
    print("=" * 56)
    amt_str = f"{data.amount:.2f}" if data.amount is not None else "--"
    print(f"  Amount:      {amt_str}")
    print(f"  Category:    {data.category or '--'}")
    print(f"  Date:        {data.date or '--'}")
    print(f"  Description: {data.description or '(none)'}")
    print("=" * 56)
    print(f"  File:        {state.file_name or state.file_path or ''}")
    print("=" * 56)
    print()

    while True:
        response = input("Log this expense? (y = approve / n = reject): ").strip()
        if response in ("y", "Y"):
            print("[APPROVED] Proceeding to save.\n")
            return {"status": ProcessingStatus.APPROVED, "approved": True}
        if response in ("n", "N"):
            print("[REJECTED] Expense will not be saved.\n")
            return {"status": ProcessingStatus.REJECTED, "approved": False}
        print("Enter 'y' to approve or 'n' to reject.")


def save_to_db_node(state: AgentState) -> dict:
    """
    Commit approved expense to Spendly SQLite.
    Only run if human_approval_node set approved=True.
    """
    if not state.approved:
        return {"status": ProcessingStatus.REJECTED}

    data = state.extracted_data
    if data is None or data.amount is None or data.amount <= 0:
        return {"status": ProcessingStatus.ERROR, "error_message": "Invalid or missing amount -- cannot save."}

    try:
        uid = state.user_id or _resolve_user_id()
        expense_id = create_expense(
            user_id=uid,
            amount=float(data.amount),
            category=data.category,
            date=data.date,
            description=data.description,
        )
        print(
            f"[DB] Saved -- id={expense_id}, amount={data.amount}, "
            f"category={data.category}, date={data.date}"
        )
        return {"status": ProcessingStatus.SAVED}
    except Exception as exc:
        return {"status": ProcessingStatus.ERROR, "error_message": f"Database write failed: {exc}"}


def error_handler_node(state: AgentState) -> dict:
    print(f"[ERROR] {state.error_message or 'Unknown error'}")
    return {"status": ProcessingStatus.ERROR}


# ------------------------------------------------------------------ #
# Conditional routing                                                #
# ------------------------------------------------------------------ #

def route_after_validate(state: AgentState) -> str:
    if state.status == ProcessingStatus.ERROR:
        return "error_handler"
    return "human_approval"


def route_after_approval(state: AgentState) -> str:
    if state.approved:
        return "save_to_db"
    return "__end__"


def route_after_save(state: AgentState) -> str:
    return "__end__"


# ------------------------------------------------------------------ #
# Build LangGraph StateGraph                                          #
# ------------------------------------------------------------------ #

def build_graph():
    from langgraph.graph import StateGraph, END

    builder = StateGraph(AgentState)

    builder.add_node("extract_receipt",  extract_receipt_node)
    builder.add_node("validate_data",    validate_data_node)
    builder.add_node("human_approval",   human_approval_node)
    builder.add_node("save_to_db",       save_to_db_node)
    builder.add_node("error_handler",    error_handler_node)

    builder.add_edge("extract_receipt", "validate_data")

    builder.add_conditional_edges(
        "validate_data",
        route_after_validate,
        {
            "error_handler": "error_handler",
            "human_approval": "human_approval",
        },
    )

    builder.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "save_to_db": "save_to_db",
            "__end__": END,
        },
    )

    builder.add_edge("save_to_db", END)
    builder.add_edge("error_handler", END)

    builder.set_entry_point("extract_receipt")

    return builder.compile(debug=False)


# ------------------------------------------------------------------ #
# Polling + orchestration                                             #
# ------------------------------------------------------------------ #

INCOMING_DIR = _AGENT_DIR / "incoming_receipts"


def process_file(graph, path: Path, user_id: int) -> bool:
    """Run graph for one receipt file. Returns True if no ERROR occurred."""
    initial_state = AgentState(
        file_path=str(path),
        file_name=path.name,
        user_id=user_id,
        status=ProcessingStatus.PENDING,
    )

    print(f"\n[GRAPH] Starting pipeline for: {path.name}")

    try:
        result = graph.invoke(initial_state)
    except Exception as exc:
        sys.stderr.write(f"[GRAPH] Invocation error: {exc}\n")
        try:
            path.rename(_processed_name(path))
        except OSError:
            pass
        return False

    final_status = result.get("status", ProcessingStatus.ERROR)
    print(f"[GRAPH] Finished: {path.name} -> {final_status}")

    if final_status == ProcessingStatus.SAVED:
        print(f"[OK] {path.name} saved to database.")
    elif final_status == ProcessingStatus.REJECTED:
        print(f"[SKIP] {path.name} -- human rejected.")
    elif final_status == ProcessingStatus.ERROR:
        print(f"[ERR] {path.name} -- {result.get('error_message', 'unknown error')}")

    try:
        path.rename(_processed_name(path))
    except OSError:
        pass

    return final_status != ProcessingStatus.ERROR


def run():
    print("\n" + "=" * 60)
    print("  Spendly Receipt Auditor -- LangGraph Edition")
    print("  Ctrl-C to stop")
    print("=" * 60)
    print(f"  Incoming   : {INCOMING_DIR}")
    print(f"  Database   : {DB_PATH}")
    print(f"  Groq model : {GROQ_MODEL}")
    print(f"  Groq key   : {'[OK]' if GROQ_API_KEY else '[MISSING]'}")
    print(f"  Groq timeout: {GROQ_TIMEOUT}s")
    print(f"  Poll every : {POLL_INTERVAL}s")
    print("=" * 60 + "\n")

    uid = _resolve_user_id()
    graph = build_graph()
    print("[INFO] Graph compiled. Watching for receipts ...\n")

    while True:
        try:
            for path in _poll_files():
                if path.suffix == ".processed":
                    continue
                process_file(graph, path, uid)
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n[INFO] Shutdown requested -- exiting.")
            break


if __name__ == "__main__":
    run()