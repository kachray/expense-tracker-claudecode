"""
expense_auditor_agent/agent_loop.py
====================================
Standalone receipt auditor script.
Polls incoming_receipts/ for new image/PDF files, sends them to a
miniMax/m2.7 vision endpoint via the OpenAI SDK over an NVIDIA NIM
proxy, then prompts for human confirmation before writing to the
Spendly SQLite database.
"""

import os
import sys
import time
import base64
import json
from datetime import date
from pathlib import Path
from typing import Optional

# ------------------------------------------------------------------ #
# OpenAI SDK client                                                   #
# ------------------------------------------------------------------ #
try:
    from openai import OpenAI
except ImportError:
    sys.stderr.write(
        "[ERROR] 'openai' package not found.  Install it with:\n"
        "  pip install openai pillow\n"
    )
    sys.exit(1)

# ------------------------------------------------------------------ #
# Image processing                                                    #
# ------------------------------------------------------------------ #
try:
    from PIL import Image
except ImportError:
    sys.stderr.write(
        "[ERROR] 'Pillow' package not found.  Install it with:\n"
        "  pip install pillow\n"
    )
    sys.exit(1)

# ------------------------------------------------------------------ #
# Import create_expense from the parent project's db module           #
# ------------------------------------------------------------------ #
# Build the path to the main project's database.db (sibling to this folder)
_AGENT_DIR = Path(__file__).resolve().parent          # .../expense_auditor_agent/
_PROJECT_ROOT = _AGENT_DIR.parent                      # .../spendly/
_PARENT_DB_PATH = _PROJECT_ROOT / "database" / "db.py"

if not _PARENT_DB_PATH.exists():
    sys.stderr.write(
        f"[ERROR] Spendly database module not found at {_PARENT_DB_PATH}\n"
    )
    sys.exit(1)

# Prepend project root so the db module resolves correctly
sys.path.insert(0, str(_PROJECT_ROOT))
from database.db import create_expense, get_db

# ------------------------------------------------------------------ #
# Configuration                                                       #
# ------------------------------------------------------------------ #
INCOMING_DIR = _AGENT_DIR / "incoming_receipts"

# NIM proxy / gateway
NIM_BASE_URL = os.environ.get("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
# API key — required when targeting NVIDIA NIM; optional for other proxies
NIM_API_KEY = os.environ.get("NIM_API_KEY", "").strip() or "not-supplied"

# Vision model identifier.
# Default matches MiniMax's m2.7-flash vision chat model on NIM.
# Override with NIM_MODEL env var.
NIM_MODEL = os.environ.get("NIM_MODEL", "minimaxi/minimax-2.7-flash")

POLL_INTERVAL_SECONDS = float(os.environ.get("AUDITOR_POLL_INTERVAL", "5"))

# The 7 categories accepted by spendly (must match app.py VALID_CATEGORIES)
VALID_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]

# Resolved at runtime
AUDITOR_USER_ID: Optional[int] = None


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _get_or_create_auditor_user() -> int:
    """Resolve the auditor's user id — uses the seeded demo user if present."""
    global AUDITOR_USER_ID
    if AUDITOR_USER_ID is not None:
        return AUDITOR_USER_ID

    conn = get_db()
    row = conn.execute(
        "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
    ).fetchone()
    conn.close()

    if row:
        AUDITOR_USER_ID = row["id"]
        print(f"[INFO] Auditor will log expenses under user id {AUDITOR_USER_ID} (demo@spendly.com).")
        return AUDITOR_USER_ID

    # No demo user — use the first user in the DB, or abort
    conn = get_db()
    row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    conn.close()

    if not row:
        sys.stderr.write(
            "[ERROR] No users found in the database.  Create a user in Spendly first.\n"
        )
        sys.exit(1)

    AUDITOR_USER_ID = row["id"]
    print(f"[INFO] Auditor will log expenses under user id {AUDITOR_USER_ID}.")
    return AUDITOR_USER_ID


def _poll_files() -> list[Path]:
    """Return image/PDF files in INCOMING_DIR sorted by mtime (oldest first)."""
    if not INCOMING_DIR.is_dir():
        INCOMING_DIR.mkdir(parents=True, exist_ok=True)

    supported = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}
    files = [
        p for p in INCOMING_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in supported
    ]
    files.sort(key=lambda p: p.stat().st_mtime)
    return files


def _load_image(path: Path) -> Image.Image:
    """Load any image file (including PDF pages) with Pillow."""
    try:
        img = Image.open(path)
        # PDF pages come back as mode "1" or "RGB" — convert to RGB for encoding
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img
    except Exception as exc:
        raise RuntimeError(f"Failed to load image {path}: {exc}") from exc


def _image_to_base64_url(img: Image.Image, fmt: str = "PNG") -> str:
    """
    Encode a Pillow Image as a base64 data URL of the given format.
    OpenAI vision expects format:  data:image/<fmt>;base64,<base64_data>
    """
    buf = BytesIO()
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/{fmt.lower()};base64,{b64}"


# ------------------------------------------------------------------ #
# Vision prompt                                                       #
# ------------------------------------------------------------------ #

VISION_SYSTEM_PROMPT = f"""\
You are a receipt-parsing assistant.  Your task is to extract structured
expense data from a receipt image or PDF page.  Return ONLY a JSON object
with these exact fields and nothing else:

{{
  "amount": <float — the total amount charged>,
  "category": <one of: {", ".join(VALID_CATEGORIES)}>,
  "date": <YYYY-MM-DD — the date on the receipt>,
  "description": <a short text description of what was purchased, or null>
}}

Rules:
- amount: parse any currency symbols or commas; return as a plain float
- category: pick the single best match from the allowed list above
- date: use the date printed on the receipt; if not clearly visible,
  use today's date ({date.today().isoformat()})
- description: summarise the merchant / purchase in ≤ 80 characters;
  use null if the receipt is illegible or contains no useful text
- Do NOT include any markdown fences, code blocks, or extra commentary.
  Return only the raw JSON object.
"""


from io import BytesIO


def _extract_with_nim(image_path: Path) -> dict:
    """
    Load the image/PDF with Pillow and send it to the NIM vision endpoint
    using the standard OpenAI vision payload format.
    """
    ext = image_path.suffix.lower()

    # Determine MIME type and Pillow format for encoding
    if ext == ".pdf":
        # Try to render the first page of the PDF
        try:
            img = _load_image(image_path)
        except Exception as exc:
            raise RuntimeError(
                f"Could not open PDF {image_path.name}.  "
                "Is the file a valid PDF?  Error: " + str(exc)
            ) from exc
        mime = "image/png"   # PDFs are rendered as PNG
        fmt = "PNG"
    elif ext in (".gif", ".webp"):
        # PIL can load these but saving as PNG is safer for base64 round-trip
        img = _load_image(image_path)
        mime = f"image/{ext.strip('.')}"
        fmt = "PNG"
    else:
        img = _load_image(image_path)
        # Infer MIME from suffix
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".bmp": "image/bmp",
        }
        mime = mime_map.get(ext, "image/png")
        fmt = "PNG" if ext == ".png" else "JPEG"

    # Build the base64 data URL — OpenAI vision standard format
    image_data_url = _image_to_base64_url(img, fmt=fmt)

    file_size = image_path.stat().st_size
    print(f"[DEBUG] Sending {image_path.name} ({file_size:,} bytes, {mime}) to {NIM_MODEL} at {NIM_BASE_URL} …")

    # ------------------------------------------------------------------ #
    # OpenAI SDK client — targets the NIM proxy                           #
    # ------------------------------------------------------------------ #
    client = OpenAI(
        base_url=NIM_BASE_URL,
        api_key=NIM_API_KEY,
    )

    response = client.chat.completions.create(
        model=NIM_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "system",
                "content": VISION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data_url,
                            "detail": "high",
                        },
                    }
                ],
            }
        ],
    )

    raw = response.choices[0].message.content.strip()
    print(f"[DEBUG] Raw model response:\n{raw}\n")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model did not return valid JSON: {exc}\nResponse was: {raw}") from exc

    # Validate required keys
    for key in ("amount", "category", "date", "description"):
        if key not in data:
            raise RuntimeError(f"Model response missing required key '{key}'.")

    return data


def _normalise_category(category: str) -> str:
    """Case-insensitive match against VALID_CATEGORIES; fall back to 'Other'."""
    for valid in VALID_CATEGORIES:
        if valid.lower() == category.lower():
            return valid
    # Try substring match
    for valid in VALID_CATEGORIES:
        if valid.lower() in category.lower():
            return valid
    print(f"[WARN] Could not match category '{category}' — defaulting to 'Other'.")
    return "Other"


# ------------------------------------------------------------------ #
# Human-in-the-loop validation                                        #
# ------------------------------------------------------------------ #

def _prompt_user(data: dict) -> bool:
    """
    Print extracted data and ask for confirmation.
    Returns True if user types 'y' / 'Y', False for 'n' / 'N'.
    """
    print("\n" + "=" * 55)
    print("  EXTRACTED RECEIPT DATA")
    print("=" * 55)
    print(f"  Amount:      {data['amount']:.2f}")
    print(f"  Category:    {data['category']}")
    print(f"  Date:        {data['date']}")
    desc = data["description"] if data["description"] else "(none)"
    print(f"  Description: {desc}")
    print("=" * 55)
    print()

    while True:
        response = input("Do you want to log this expense? (y/n): ").strip()
        if response in ("y", "Y"):
            return True
        if response in ("n", "N"):
            return False
        print("Please enter 'y' or 'n'.")


# ------------------------------------------------------------------ #
# Processed-file tracking                                             #
# ------------------------------------------------------------------ #

def _processed_name(path: Path) -> Path:
    """Return path with '.processed' appended."""
    return path.with_name(path.name + ".processed")


# ------------------------------------------------------------------ #
# Entry point                                                         #
# ------------------------------------------------------------------ #

def run():
    print("\n============================================================")
    print("  Spendly Receipt Auditor Agent  (Ctrl-C to stop)")
    print("============================================================")
    print(f"  Incoming folder : {INCOMING_DIR}")
    print(f"  Database        : {_PROJECT_ROOT / 'spendly.db'}")
    print(f"  NIM base URL    : {NIM_BASE_URL}")
    print(f"  Model           : {NIM_MODEL}")
    print(f"  API key set     : {'yes' if NIM_API_KEY and NIM_API_KEY != 'not-supplied' else 'no'}")
    print(f"  Poll interval   : {POLL_INTERVAL_SECONDS}s")
    print("============================================================\n")

    _get_or_create_auditor_user()

    print(f"[INFO] Watching {INCOMING_DIR} for new receipts …\n")

    while True:
        try:
            files = _poll_files()
            for path in files:
                # Skip already-processed files (identified by .processed suffix)
                if path.suffix == ".processed":
                    continue

                print(f"\n[NEW FILE] {path.name}")

                try:
                    data = _extract_with_nim(path)
                except Exception as exc:
                    sys.stderr.write(f"[ERROR] Vision extraction failed for {path.name}: {exc}\n")
                    # Rename to .processed so corrupt/unreadable files are not retried
                    try:
                        path.rename(_processed_name(path))
                    except OSError:
                        pass
                    continue

                # Normalise category to a valid Spendly category
                data["category"] = _normalise_category(data.get("category", ""))

                # Human-in-the-loop confirmation
                confirmed = _prompt_user(data)

                if confirmed:
                    uid = _get_or_create_auditor_user()
                    expense_id = create_expense(
                        user_id=uid,
                        amount=float(data["amount"]),
                        category=data["category"],
                        date=data["date"],
                        description=data.get("description"),
                    )
                    print(f"[OK] Expense logged with id={expense_id}.")
                    try:
                        path.rename(_processed_name(path))
                    except OSError:
                        pass
                else:
                    print(f"[SKIP] Expense NOT logged.  Moving {path.name} to processed anyway.")
                    try:
                        path.rename(_processed_name(path))
                    except OSError:
                        pass

            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\n[INFO] Shutting down auditor agent.")
            break


if __name__ == "__main__":
    run()