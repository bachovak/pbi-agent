import anthropic
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

LIBRARY_FILE = "measure_library.json"

# ── Model Inspector ───────────────────────────────────────────────────────────

def load_model(bim_path):
    with open(bim_path, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_schema(model):
    schema = {"tables": [], "relationships": []}
    tables = model.get("model", {}).get("tables", [])

    for table in tables:
        table_name = table.get("name")
        if table.get("isHidden") or table_name.startswith("DateTableTemplate"):
            continue

        columns = []
        for col in table.get("columns", []):
            if col.get("type") == "calculated":
                continue
            columns.append({
                "name": col.get("name"),
                "dataType": col.get("dataType", "unknown")
            })

        measures = []
        for measure in table.get("measures", []):
            measures.append({
                "name": measure.get("name"),
                "expression": expr.strip() if isinstance(expr := measure.get("expression", ""), str) else " ".join(expr).strip()
            })

        schema["tables"].append({
            "name": table_name,
            "columns": columns,
            "measures": measures
        })

    relationships = model.get("model", {}).get("relationships", [])
    for rel in relationships:
        schema["relationships"].append({
            "from": f"{rel.get('fromTable')}[{rel.get('fromColumn')}]",
            "to": f"{rel.get('toTable')}[{rel.get('toColumn')}]"
        })

    return schema

def format_schema_for_prompt(schema):
    lines = []
    lines.append("=== POWER BI DATA MODEL ===")
    lines.append("")

    for table in schema["tables"]:
        lines.append(f"TABLE: {table['name']}")
        if table["columns"]:
            lines.append("  Columns:")
            for col in table["columns"]:
                lines.append(f"    - {col['name']} ({col['dataType']})")
        if table["measures"]:
            lines.append("  Existing Measures:")
            for m in table["measures"]:
                lines.append(f"    - {m['name']}: {m['expression']}")
        lines.append("")

    if schema["relationships"]:
        lines.append("RELATIONSHIPS:")
        for rel in schema["relationships"]:
            lines.append(f"  - {rel['from']} -> {rel['to']}")
    else:
        lines.append("RELATIONSHIPS: None defined yet")

    lines.append("")
    lines.append("=== END OF MODEL ===")
    return "\n".join(lines)

# ── Measure Library ───────────────────────────────────────────────────────────

def load_library():
    if os.path.exists(LIBRARY_FILE):
        with open(LIBRARY_FILE, "r") as f:
            return json.load(f)
    return []

def save_to_library(user_request, dax, attempts_taken):
    library = load_library()
    entry = {
        "id": len(library) + 1,
        "request": user_request,
        "dax": dax,
        "attempts_taken": attempts_taken,
        "created_at": datetime.now().isoformat()
    }
    library.append(entry)
    with open(LIBRARY_FILE, "w") as f:
        json.dump(library, f, indent=2)
    return entry["id"]

# ── DAX Generator ─────────────────────────────────────────────────────────────

def generate_dax(user_request, model_context, previous_attempt=None, feedback=None):
    if previous_attempt and feedback:
        content = f"""Request: {user_request}

Your previous attempt was:
{previous_attempt}

That attempt failed validation with this feedback:
{feedback}

Please fix the issue and try again.
Remember to only use tables and columns that exist in the data model below."""
    else:
        content = f"Request: {user_request}"

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=f"""You are an expert Power BI DAX developer.
You will be given a business measure request and a data model to work with.
You must ONLY use tables and columns that exist in the data model.
Do NOT invent table or column names.
Respond with ONLY the DAX measure code — no explanations, no markdown, no backticks.

Example output format:
Total Revenue = SUM(Fact_DailyFlash[TotalRevenue])

Here is the data model you must use:

{model_context}""",
        messages=[
            {"role": "user", "content": content}
        ]
    )
    raw = message.content[0].text
# Strip markdown code fences if Claude added them
raw = raw.strip()
if raw.startswith("```"):
    lines = raw.split("\n")
    # Remove first line (```dax or ```) and last line (```)
    lines = [l for l in lines if not l.strip().startswith("```")]
    raw = "\n".join(lines).strip()
return raw

# ── Validators ────────────────────────────────────────────────────────────────

def validate_structural(dax):
    issues = []
    if "=" not in dax:
        issues.append("Missing measure name — no equals sign found")
    if "[" not in dax or "]" not in dax:
        issues.append("No column references found — may be incomplete")
    if len(dax.strip()) < 10:
        issues.append("Output is too short — may not be valid DAX")
    return issues

def validate_columns_exist(dax, schema):
    """Check that every Table[Column] reference in the DAX exists in the model."""
    import re
    issues = []

    # Build a lookup of valid table[column] pairs
    valid_refs = set()
    table_names = set()
    for table in schema["tables"]:
        table_names.add(table["name"].lower())
        for col in table["columns"]:
            valid_refs.add(f"{table['name'].lower()}[{col['name'].lower()}]")
        for measure in table["measures"]:
            valid_refs.add(f"{table['name'].lower()}[{measure['name'].lower()}]")

    # Find all Table[Column] references in the DAX
    pattern = r"(\w+)\[([^\]]+)\]"
    matches = re.findall(pattern, dax)

    for table, column in matches:
        ref = f"{table.lower()}[{column.lower()}]"
        if table.lower() in table_names and ref not in valid_refs:
            issues.append(f"Column not found in model: {table}[{column}]")

    return issues

def validate_semantic(user_request, dax, model_context):
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=f"""You are a Power BI DAX code reviewer.
You will be given a business request, a DAX measure, and the data model it was built for.
Check if the DAX correctly answers the request using only valid columns from the model.

Respond in this exact format and nothing else:
PASS: <one sentence explaining why it is correct>
or
FAIL: <one sentence explaining what is wrong>

Data model for reference:
{model_context}""",
        messages=[
            {"role": "user", "content": f"Request: {user_request}\n\nDAX: {dax}"}
        ]
    )
    return message.content[0].text

# ── Main Flow ─────────────────────────────────────────────────────────────────

def main():
    # Load the model
    bim_path = r"C:\Users\v-krb\OneDrive\Freelance Portugal 2026\Power BI - Claude Agent Platform\pbi-agent\Model.bim"
    print("\nReading model...")
    model = load_model(bim_path)
    schema = extract_schema(model)
    model_context = format_schema_for_prompt(schema)
    print(f"Model loaded: {len(schema['tables'])} tables found.")

    print("\nType 'quit' to exit.\n")

    while True:
        user_request = input("What DAX measure do you need? ").strip()
        if user_request.lower() == "quit":
            break

        max_attempts = 3
        attempt = 1
        previous_dax = None
        previous_feedback = None
        success = False

        while attempt <= max_attempts:
            print(f"\n  Attempt {attempt} of {max_attempts}...")

            dax = generate_dax(
                user_request, model_context, previous_dax, previous_feedback
            )

            # Structural check
            structural_issues = validate_structural(dax)
            if structural_issues:
                print(f"  Structural issues: {structural_issues}")
                previous_dax = dax
                previous_feedback = " | ".join(structural_issues)
                attempt += 1
                continue

            # Column existence check
            column_issues = validate_columns_exist(dax, schema)
            if column_issues:
                print(f"  Column issues: {column_issues}")
                previous_dax = dax
                previous_feedback = " | ".join(column_issues)
                attempt += 1
                continue

            print("  Structural + column validation passed.")

            # Semantic check
            semantic_result = validate_semantic(user_request, dax, model_context)
            print(f"  Semantic: {semantic_result}")

            if semantic_result.startswith("PASS"):
                measure_id = save_to_library(user_request, dax, attempt)
                print(f"\n✓ Saved as measure #{measure_id}")
                print("\nFinal DAX:")
                print(dax)
                success = True
                break
            else:
                previous_dax = dax
                previous_feedback = semantic_result
                attempt += 1

        if not success:
            print("\n✗ Could not generate valid DAX after 3 attempts.")
            print(f"Last attempt: {dax}")

        print()

if __name__ == "__main__":
    main()