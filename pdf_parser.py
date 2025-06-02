# pdf_parser.py

import os
import json
import pandas as pd
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Replace with your actual Vector Store ID
VECTOR_STORE_ID = "vs_683bf1a7c1848191a3eac3d947ee8873"


def _upload_single_pdf_to_vector(file_path: str) -> bool:
    """
    Uploads one PDF to the OpenAI vector store so that file_search can see it.
    If the file is already present (same filename) in the vector store, skip uploading.
    Returns True if the file is already present or upload succeeded, False otherwise.
    """
    file_name = os.path.basename(file_path)

    # 1) Check existing files in the vector store
    try:
        existing_filenames = set()
        resp = client.vector_stores.files.list(vector_store_id=VECTOR_STORE_ID)
        for entry in resp.data:
            try:
                fid = entry.file_id
            except AttributeError:
                fid = entry.id
            # Retrieve the file metadata to get its filename
            fobj = client.files.retrieve(fid)
            existing_filenames.add(fobj.filename)
    except Exception as e:
        print(f"[Upload Error] Could not list existing vector-store files: {e}")
        # Proceed with upload attempt anyway

    # 2) If filename already present, skip upload
    if file_name in existing_filenames:
        print(
            f"[Upload Info] `{file_name}` is already in the vector store; skipping upload."
        )
        return True

    # 3) Otherwise, attempt to upload
    try:
        with open(file_path, "rb") as f:
            file_resp = client.files.create(file=f, purpose="assistants")
        client.vector_stores.files.create(
            vector_store_id=VECTOR_STORE_ID, file_id=file_resp.id
        )
        return True

    except FileNotFoundError:
        print(f"[Upload Error] File not found: {file_path}")
        return False

    except PermissionError as perm:
        print(f"[Upload Error] Permission denied when opening `{file_path}`: {perm}")
        return False

    except Exception as e:
        print(f"[Upload Error] Unexpected error uploading `{file_name}`: {e}")
        return False


def _extract_transactions_from_openai(filenames: list[str]) -> list[dict]:
    """
    Given a list of filenames (e.g. ["statement1.pdf", "statement2.pdf"]),
    ask GPT-4o to extract all individual transactions as JSON,
    then parse and return as Python list of dicts.
    Strips out any markdown fences (``` or ```json) before parsing.
    If the JSON parse fails, prints the raw text and returns an empty list.
    """
    # Build a comma‐separated quoted list for the prompt, e.g. "\"a.pdf\", \"b.pdf\""
    quoted = ", ".join(f'"{fn}"' for fn in filenames)
    prompt = f"""
Extract all valid, individual transactions from the following newly‐uploaded credit card statements: {quoted}.
Return the result as a single JSON array of objects, where each object has exactly these keys:
- "Date" (e.g. "19 APR"),
- "Description" (merchant name or transaction description),
- "Amount" (numeric value, positive for charges, negative for credits),
- "Currency" (e.g. "SGD").

Example format:
[
  {{
    "Date": "19 APR",
    "Description": "MERCHANT NAME",
    "Amount": 12.34,
    "Currency": "SGD"
  }},
  {{
    "Date": "20 APR",
    "Description": "OTHER STORE",
    "Amount": 45.67,
    "Currency": "SGD"
  }}
]

**Important**: Only output the JSON array—do not include any extra text, explanation, or fields.
"""
    # Call GPT-4o with file_search enabled
    response = client.responses.create(
        input=prompt,
        model="gpt-4.1",
        tools=[{"type": "file_search", "vector_store_ids": [VECTOR_STORE_ID]}],
    )

    try:
        raw_text = response.output[1].content[0].text
    except Exception as e:
        # If we can’t even find .text, just bail:
        print(f"[Extract Error] No text found in GPT response: {e}")
        return []

    # Strip leading/trailing whitespace and remove markdown fences if present
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence (and any "```json" label)
        idx = cleaned.find("\n")
        if idx != -1:
            cleaned = cleaned[idx + 1 :].lstrip()
    if cleaned.endswith("```"):
        # Drop the closing fence
        cleaned = cleaned[: cleaned.rfind("```")].rstrip()

    # Try a direct JSON parse on the cleaned string
    try:
        data = json.loads(cleaned)
        return data  # a list of dicts
    except json.JSONDecodeError as je:
        # Parsing failed—print the raw and cleaned texts for debugging
        print(f"[Extract Error] JSON decoding failed: {je}")
        print("Raw GPT response (unparseable):")
        print(raw_text)
        print("\nCleaned text passed to json.loads:")
        print(cleaned)
        return []


def parse_pdf(file_path: str) -> pd.DataFrame:
    """
    1) Uploads the given PDF to the vector store
    2) Queries GPT-4o to extract all transactions from that file
    3) Returns a DataFrame with columns [Date, Description, Amount, Currency]

    If parsing fails at any point, returns an empty DataFrame with those columns.
    """
    file_name = os.path.basename(file_path)
    uploaded = _upload_single_pdf_to_vector(file_path)
    if not uploaded:
        return pd.DataFrame(columns=["Date", "Description", "Amount", "Currency"])

    # We only just uploaded one file, so ask OpenAI to parse that single filename
    transactions = _extract_transactions_from_openai([file_name])
    if not transactions:
        return pd.DataFrame(columns=["Date", "Description", "Amount", "Currency"])

    # Build DataFrame. Any missing keys will become NaN.
    df = pd.DataFrame(transactions)
    for col in ["Date", "Description", "Amount", "Currency"]:
        if col not in df.columns:
            df[col] = None

    # Ensure Amount is numeric
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    return df[["Date", "Description", "Amount", "Currency"]]
