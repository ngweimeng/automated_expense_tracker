import os
import pandas as pd
import subprocess
import tempfile

# Default currency for transactions
DEFAULT_CURRENCY = "SGD"


def parse_pdf(file_path: str) -> pd.DataFrame:
    """
    Uses the `monopoly` CLI to convert a PDF bank statement into a CSV,
    then loads it into a DataFrame with columns [Date, Description, Amount, Currency].

    If parsing fails, returns an empty DataFrame with those columns.
    """
    # Create a temporary output directory for CSV
    output_dir = tempfile.mkdtemp(prefix="monopoly_output_")

    # Build and run the monopoly command
    cmd = ["monopoly", "--output", output_dir, file_path]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[Parse Error] `monopoly` failed: {e.stderr.strip()}")
        return pd.DataFrame(columns=["Date", "Description", "Amount", "Currency"])

    # Determine CSV file name: same base name as PDF
    base = os.path.splitext(os.path.basename(file_path))[0]
    csv_path = os.path.join(output_dir, f"{base}.csv")

    # Fallback: pick any CSV if naming differs
    if not os.path.exists(csv_path):
        csv_files = [f for f in os.listdir(output_dir) if f.lower().endswith(".csv")]
        if not csv_files:
            print("[Parse Error] No CSV output found in monopoly output directory.")
            return pd.DataFrame(columns=["Date", "Description", "Amount", "Currency"])
        csv_path = os.path.join(output_dir, csv_files[0])

    # Load the CSV
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"[Parse Error] Failed to read CSV {csv_path}: {e}")
        return pd.DataFrame(columns=["Date", "Description", "Amount", "Currency"])

    # Normalize column names
    df = df.rename(
        columns={
            "date": "Date",
            "description": "Description",
            "amount": "Amount",
        }
    )

    # Ensure required columns exist
    for col in ["Date", "Description", "Amount"]:
        if col not in df.columns:
            df[col] = None

    # Ensure Amount is numeric
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")

    # MANUAL LOGIC:
    ## (1) negatives → positives, positives → negatives
    df["Amount"] = -df["Amount"]

    ## (2) Remove rows with "PREVIOUS BALANCE" OR "PAYMENT - DBS INTERNET/WIRELESS" in DBS credit statements
    desc_clean = (
        df["Description"]
        .fillna("")  # no NaN
        .str.strip()  # trim whitespace
        .str.upper()  # uppercase
    )
    bad = [
        "PREVIOUS BALANCE",
        "PAYMENT - DBS INTERNET/WIRELESS",
        "BALANCE PREVIOUS STATEMENT",
        "MONEYSEND NG WEI MENG SINGAPORE SG",
    ]
    mask_prev = desc_clean.isin(bad)
    df = df.loc[~mask_prev]

    ## (3) Remove any leading "AMAZE* " and trailing " SINGAPORE SG" in description from Citibank credit statements
    df["Description"] = df["Description"].str.replace(
        r"(?i)^AMAZE\*\s*(.*?)\s*SINGAPORE\s+SG$",
        r"\1",
        regex=True,
    )

    ## (4) collapse "Grab* CODE LOCATION" → "Grab LOCATION" Citibank credit statements──────────────
    df["Description"] = df["Description"].str.replace(
        # (?i)       ignore case
        # ^(Grab)\*  capture "Grab" at start, literally "*"
        # \s+        one or more spaces
        # [A-Z0-9-]+ the code (caps, digits, dashes)
        # \s+        spaces
        # (.+)$      capture the rest (the location) up to end
        r"(?i)^(Grab)\*\s+[A-Z0-9-]+\s+(.+)$",
        r"\1 \2",  # replace with "Grab <location>"
        regex=True,
    )

    ## (5) Drop the trailing amount for any “CONVERSION FEE” description ──
    mask_conv = df["Description"].str.contains("CONVERSION FEE", case=False, na=False)
    df.loc[mask_conv, "Description"] = df.loc[mask_conv, "Description"].str.replace(
        r"\s+[A-Z]{3}\s+\d+(\.\d+)?$", "", regex=True
    )

    # Fill Currency
    df["Currency"] = DEFAULT_CURRENCY

    return df[["Date", "Description", "Amount", "Currency"]]


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python pdf_parser.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    df = parse_pdf(pdf_path)
    if df.empty:
        print("No transactions extracted.")
    else:
        print(df.to_string(index=False))
