import anthropic
import json
import os
import re
from datetime import datetime
from dotenv import load_dotenv

from model_inspector import (
    load_model,
    extract_schema,
    format_schema_for_prompt,
    build_model_registry,
    format_registry_for_prompt,
)
from sanitiser import SemanticReferenceValidator

load_dotenv()

client = anthropic.Anthropic()

LIBRARY_FILE = "measure_library.json"

# ── Measure Library ───────────────────────────────────────────────────────────

def load_library():
    if os.path.exists(LIBRARY_FILE):
        with open(LIBRARY_FILE, "r") as f:
            return json.load(f)
    return []
def check_for_duplicate(user_request, library):
    """Check if a similar measure already exists in the library."""
    if not library:
        return None

    # Format existing measures as a summary for Claude to review
    existing = []
    for entry in library:
        existing.append(f"ID {entry['id']}: {entry['request']} => {entry['dax']}")
    existing_text = "\n".join(existing)

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system="""You are a Power BI measure library manager checking for duplicate measures.
Two measure requests are duplicates if they are asking for the same business calculation,
even if they use different wording. For example:
- "room revenue this year" and "total room revenue for the current year" ARE duplicates
- "total revenue" and "revenue this year" are NOT duplicates (different time scope)
- "average ADR" and "total ADR" are NOT duplicates (different aggregation)

Be aggressive about catching duplicates — if in doubt, flag it.

Respond in this exact format and nothing else:
DUPLICATE: <id number> — <one sentence explaining why it matches>
or
NEW: <one sentence explaining why no existing measure matches>""",
        messages=[
            {"role": "user", "content": f"New request: {user_request}\n\nExisting measures:\n{existing_text}"}
        ]
    )
    return message.content[0].text

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

# System prompt constraint block injected when a model registry is available.
# Sourced from: analysis of data-goblin/power-bi-agentic-development (GPL v3) —
# patterns E2 (DON'T MAKE ASSUMPTIONS), E4 (fully-qualified refs), B1/B2
# (existence checks), F2 (summarizeBy semantic rules), F3 (compat gating).
_REGISTRY_CONSTRAINT = """
## MODEL OBJECT CONSTRAINT — READ THIS FIRST

The Model Object Registry below is the authoritative list of every table,
column, and measure that exists in this model. You are STRICTLY CONSTRAINED
to reference only objects that appear in it.

RULES — violating any of these will cause the measure to fail validation:

1. NEVER invent, guess, or infer object names. If you need an object that
   is not in the registry, say so explicitly instead of generating a
   reference to it.

2. All column references MUST use single-quoted table names:
      CORRECT : 'Sales'[Amount]
      WRONG   : Sales[Amount]  or  [Amount]  or  Sales[Amount]

3. Measure references are always unqualified bracket notation:
      CORRECT : [Total Revenue]
      WRONG   : 'Sales'[Total Revenue]  or  Sales[Total Revenue]

4. Do NOT aggregate (SUM, AVERAGE, MIN, MAX, COUNT, DISTINCTCOUNT) any
   column tagged [no-aggregate] or [key] in the registry. These are key
   columns and attribute columns — aggregating them is semantically wrong.

5. Do NOT use SELECTEDMEASURE() unless the registry shows
   "Calculation groups: YES".

6. Do NOT use DAX UDFs (e.g. MyLib.Function()) unless the registry shows
   compatibility level >= 1702.

7. Before writing any object reference, verify it appears verbatim in the
   registry. If you are uncertain, do not write it.

{registry_block}
"""

def generate_dax(user_request, model_context, previous_attempt=None, feedback=None, model_registry=None, ref_correction=False):
    """
    Generate a DAX measure for the given request.

    model_registry: if provided (dict from build_model_registry()), the
    structured object constraint is injected into the system prompt so
    Claude is hard-constrained to only reference objects that exist.

    ref_correction: if True, use a targeted correction prompt that lists
    each reference error as a numbered item and instructs Claude to fix
    only those objects without regenerating the rest of the expression.
    """
    if ref_correction and previous_attempt and feedback:
        # T2-C: targeted reference-error correction prompt.
        # Errors are listed individually so Claude fixes each one precisely
        # rather than regenerating. Full model context is omitted to keep
        # the focus on the specific objects that need correcting.
        errors = [e.strip() for e in feedback.split(" | ") if e.strip()]
        errors_text = "\n".join(f"  {i + 1}. {e}" for i, e in enumerate(errors))
        content = f"""The DAX expression below contains reference errors.
Correct ONLY the specific objects listed below — do not change the measure name,
the calculation logic, or any other part of the expression.

EXPRESSION TO CORRECT:
{previous_attempt}

REFERENCE ERRORS TO FIX:
{errors_text}

Every corrected reference must appear verbatim in the Model Object Registry."""
    elif previous_attempt and feedback:
        content = f"""Request: {user_request}

Your previous attempt was:
{previous_attempt}

That attempt failed validation with this feedback:
{feedback}

Please fix ONLY the specific issues listed above — do not change anything else.
Every object reference must appear in the Model Object Registry."""
    else:
        content = f"Request: {user_request}"

    # Build system prompt — inject registry constraint when available
    if model_registry:
        registry_block = format_registry_for_prompt(model_registry)
        constraint_section = _REGISTRY_CONSTRAINT.format(registry_block=registry_block)
    else:
        constraint_section = (
            "\nYou must ONLY use tables and columns that exist in the data model below. "
            "Do NOT invent table or column names. "
            "Always fully qualify column references as 'TableName'[ColumnName].\n"
        )

    system_prompt = f"""You are an expert Power BI DAX developer.
{constraint_section}
Respond with ONLY the DAX measure code — no explanations, no markdown, no backticks.

Output format (one line for simple measures, multi-line for complex ones):
Measure Name = DAX expression

Here is the full data model for additional context:

{model_context}"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": content}]
    )
    raw = message.content[0].text.strip()
    # Strip markdown code fences if Claude added them anyway
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()
    return raw

# ── Validators ────────────────────────────────────────────────────────────────

def validate_structural(dax):
    issues = []
    if "=" not in dax:
        issues.append("Missing measure name — no equals sign found")
    if "[" not in dax or "]" not in dax:
        issues.append("No column or measure references found — may be incomplete")
    if len(dax.strip()) < 10:
        issues.append("Output is too short — may not be valid DAX")
    return issues


def validate_columns_exist(dax, schema):
    """
    Check that every Table[Column] reference in the DAX exists in the model.

    Handles both forms:
      'TableName'[ColumnName]   — single-quoted (correct form)
      TableName[ColumnName]     — unquoted (common LLM output, still checked)
    """
    issues = []

    # Build lookup sets
    valid_refs = set()
    table_names = set()
    for table in schema["tables"]:
        table_names.add(table["name"].lower())
        for col in table["columns"]:
            valid_refs.add(f"{table['name'].lower()}[{col['name'].lower()}]")
        for measure in table["measures"]:
            valid_refs.add(f"{table['name'].lower()}[{measure['name'].lower()}]")

    # Match both 'Table'[Column] and Table[Column]
    pattern = re.compile(r"'?([A-Za-z0-9 _$]+)'?\[([^\]]+)\]")
    for match in pattern.finditer(dax):
        table = match.group(1).strip()
        column = match.group(2).strip()
        ref = f"{table.lower()}[{column.lower()}]"
        if table.lower() in table_names and ref not in valid_refs:
            issues.append(f"Column not found in model: '{table}'[{column}]")

    return issues


def check_name_collision(dax, library):
    """
    Check if the measure name in the generated DAX exactly matches a measure
    name already saved in the library.

    Returns a warning string if a collision is found, None otherwise.
    This is a hard-name check — semantic similarity is handled separately
    by check_for_duplicate().
    """
    if not library:
        return None

    # Extract the measure name from the generated DAX (text before first =)
    match = re.match(r"^\s*([^=\[]+?)\s*=", dax)
    if not match:
        return None
    generated_name = match.group(1).strip()

    for entry in library:
        existing_match = re.match(r"^\s*([^=\[]+?)\s*=", entry.get("dax", ""))
        if existing_match:
            existing_name = existing_match.group(1).strip()
            if generated_name.lower() == existing_name.lower():
                return (
                    f"NAME COLLISION: Measure '{generated_name}' already exists "
                    f"in the library (ID {entry['id']}). This will overwrite it. "
                    f"Rename the measure or confirm the replacement."
                )
    return None

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
    bim_path = os.getenv("BIM_PATH", "Model.bim")
    print("\nReading model...")
    model = load_model(bim_path)
    schema = extract_schema(model)
    model_context = format_schema_for_prompt(schema)
    model_registry = build_model_registry(model)
    print(f"Model loaded: {len(schema['tables'])} tables, "
          f"{len(model_registry['measures'])} measures, "
          f"compat level {model_registry['compatibility_level']}.")

    print("\nType 'quit' to exit.\n")

    while True:
        user_request = input("What DAX measure do you need? ").strip()
        if user_request.lower() == "quit":
            break

        # Check for duplicates before generating anything
        print("\n  Checking measure library for similar measures...")
        library = load_library()
        duplicate_result = check_for_duplicate(user_request, library)
        print(f"  Library check: {duplicate_result}")

        if duplicate_result and duplicate_result.startswith("DUPLICATE"):
            try:
                duplicate_id = int(duplicate_result.split(":")[1].strip().split("—")[0].strip())
                existing_measure = next((m for m in library if m["id"] == duplicate_id), None)
                if existing_measure:
                    print(f"\n  Similar measure already exists in library.")
                    print(f"\n  Existing DAX:")
                    print(existing_measure["dax"])
                    choice = input("\n  Use existing measure? (yes/no): ").strip().lower()
                    if choice == "yes":
                        print("  Using existing measure. No new measure generated.")
                        print()
                        continue
                    else:
                        print("  Proceeding with new generation anyway...")
            except (ValueError, IndexError):
                print("  Could not parse duplicate ID, proceeding with generation...")

        max_attempts = 3
        max_ref_retries = 2
        attempt = 1
        ref_retry_count = 0
        ref_correction = False
        previous_dax = None
        previous_feedback = None
        success = False

        while attempt <= max_attempts:
            print(f"\n  Attempt {attempt} of {max_attempts}...")

            dax = generate_dax(
                user_request,
                model_context,
                previous_dax,
                previous_feedback,
                model_registry=model_registry,
                ref_correction=ref_correction,
            )
            ref_correction = False  # reset after each generation

            # Structural check
            structural_issues = validate_structural(dax)
            if structural_issues:
                print(f"  Structural issues: {structural_issues}")
                previous_dax = dax
                previous_feedback = " | ".join(structural_issues)
                attempt += 1
                continue

            # Semantic reference validation — column, measure, compat, aggregation
            if model_registry:
                ref_result = SemanticReferenceValidator(model_registry).validate(dax)
                if ref_result["warnings"]:
                    for w in ref_result["warnings"]:
                        print(f"  Warning: {w}")
                if not ref_result["passed"]:
                    ref_retry_count += 1
                    if ref_retry_count > max_ref_retries:
                        print(f"  Reference errors persist after {max_ref_retries} correction attempt(s) — stopping.")
                        break
                    print(f"  Reference correction {ref_retry_count}/{max_ref_retries}: {ref_result['errors']}")
                    previous_dax = dax
                    previous_feedback = " | ".join(ref_result["errors"])
                    ref_correction = True
                    attempt += 1
                    continue
            else:
                column_issues = validate_columns_exist(dax, schema)
                if column_issues:
                    print(f"  Reference issues: {column_issues}")
                    previous_dax = dax
                    previous_feedback = " | ".join(column_issues)
                    attempt += 1
                    continue

            print("  Structural + reference validation passed.")

            # Name collision check (T1-F)
            collision = check_name_collision(dax, library)
            if collision:
                print(f"\n  ⚠  {collision}")
                choice = input("  Proceed anyway? (yes/no): ").strip().lower()
                if choice != "yes":
                    print("  Cancelled. Try again with a different measure name.")
                    break

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