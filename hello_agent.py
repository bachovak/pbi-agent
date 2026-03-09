import anthropic
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

LIBRARY_FILE = "measure_library.json"

def load_library():
    """Load existing measures from the library file."""
    if os.path.exists(LIBRARY_FILE):
        with open(LIBRARY_FILE, "r") as f:
            return json.load(f)
    return []

def save_to_library(user_request, dax, attempts_taken):
    """Save a validated measure to the library."""
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

def generate_dax(user_request, previous_attempt=None, feedback=None):
    if previous_attempt and feedback:
        content = f"""Request: {user_request}

Your previous attempt was:
{previous_attempt}

That attempt failed validation with this feedback:
{feedback}

Please fix the issue and try again."""
    else:
        content = user_request

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system="""You are an expert Power BI DAX developer. 
When given a business measure request, you respond with ONLY the DAX measure code.
No explanations, no markdown, no backticks. Just the raw DAX.
Example output format:
Total Revenue = SUM(Sales[Revenue])""",
        messages=[
            {"role": "user", "content": content}
        ]
    )
    return message.content[0].text

def validate_dax_structural(dax):
    issues = []
    if "=" not in dax:
        issues.append("Missing measure name — no equals sign found")
    if "[" not in dax or "]" not in dax:
        issues.append("No column references found — may be incomplete")
    if len(dax.strip()) < 10:
        issues.append("Output is too short — may not be valid DAX")
    return issues

def validate_dax_semantic(user_request, dax):
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system="""You are a Power BI DAX code reviewer.
You will be given a business request and a DAX measure.
Your job is to check if the DAX measure correctly answers the request.

Respond in this exact format and nothing else:
PASS: <one sentence explaining why it is correct>
or
FAIL: <one sentence explaining what is wrong>""",
        messages=[
            {"role": "user", "content": f"Request: {user_request}\n\nDAX: {dax}"}
        ]
    )
    return message.content[0].text

# --- Main flow ---
user_request = input("What DAX measure do you need? ")

max_attempts = 3
attempt = 1
previous_dax = None
previous_feedback = None
success = False

while attempt <= max_attempts:
    print(f"\nAttempt {attempt} of {max_attempts}...")
    
    dax = generate_dax(user_request, previous_dax, previous_feedback)
    
    print("Running structural validation...")
    structural_issues = validate_dax_structural(dax)
    
    if structural_issues:
        print("Structural issues found:")
        for issue in structural_issues:
            print(f"  - {issue}")
        previous_dax = dax
        previous_feedback = " | ".join(structural_issues)
        attempt += 1
        continue

    print("Structural validation passed.")
    print("Running semantic validation...")
    semantic_result = validate_dax_semantic(user_request, dax)
    print(f"Semantic result: {semantic_result}")

    if semantic_result.startswith("PASS"):
        measure_id = save_to_library(user_request, dax, attempt)
        print(f"\n✓ Validation passed. Saved to library as measure #{measure_id}.")
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
    print("Last attempt:")
    print(dax)