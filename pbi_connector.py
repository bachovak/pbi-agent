import os
import requests
import msal
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────────────────────────
CLIENT_ID     = os.getenv("PBI_CLIENT_ID")
TENANT_ID     = os.getenv("PBI_TENANT_ID")
CLIENT_SECRET = os.getenv("PBI_CLIENT_SECRET")
WORKSPACE_ID  = os.getenv("PBI_WORKSPACE_ID")
DATASET_ID    = os.getenv("PBI_DATASET_ID")

AUTHORITY     = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE         = ["https://analysis.windows.net/powerbi/api/.default"]
PBI_API       = "https://api.powerbi.com/v1.0/myorg"

# ── Authentication ────────────────────────────────────────────────────────────

def get_access_token():
    """Get an access token from Azure AD using client credentials."""
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=SCOPE)

    if "access_token" in result:
        print("Authentication successful.")
        return result["access_token"]
    else:
        error = result.get("error_description", "Unknown error")
        raise Exception(f"Authentication failed: {error}")

# ── API Functions ─────────────────────────────────────────────────────────────

def get_tables(token):
    """Get all tables in the dataset."""
    url = f"{PBI_API}/groups/{WORKSPACE_ID}/datasets/{DATASET_ID}/tables"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json().get("value", [])
    else:
        raise Exception(f"Failed to get tables: {response.status_code} {response.text}")

def push_measure(token, table_name, measure_name, dax_expression):
    """Push a new measure to a specific table in the dataset."""
    url = f"{PBI_API}/groups/{WORKSPACE_ID}/datasets/{DATASET_ID}/tables/{table_name}/measures"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "name": measure_name,
        "expression": dax_expression
    }
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        return True
    else:
        raise Exception(f"Failed to push measure: {response.status_code} {response.text}")

# ── Human Approval Gate ───────────────────────────────────────────────────────

def approval_gate(measure_name, dax_expression, table_name):
    """Show the measure to the human and ask for approval before pushing."""
    print("\n" + "="*50)
    print("APPROVAL REQUIRED")
    print("="*50)
    print(f"Measure name : {measure_name}")
    print(f"Target table : {table_name}")
    print(f"DAX          :")
    print(dax_expression)
    print("="*50)

    choice = input("\nPush this measure to Power BI? (yes/no): ").strip().lower()
    return choice == "yes"

def extract_measure_name(dax):
    """Extract the measure name from DAX (the part before the = sign)."""
    if "=" in dax:
        return dax.split("=")[0].strip()
    return "New Measure"

def extract_measure_expression(dax):
    """Extract just the expression part from DAX (after the = sign)."""
    if "=" in dax:
        return "=".join(dax.split("=")[1:]).strip()
    return dax

# ── Test Connection ───────────────────────────────────────────────────────────

def test_connection():
    """Test that we can connect and see the dataset."""
    print("Testing Power BI connection...")
    token = get_access_token()
    tables = get_tables(token)
    print(f"Connected successfully. Found {len(tables)} tables:")
    for table in tables:
        print(f"  - {table['name']}")
    return token
def list_datasets(token):
    """List all datasets in the workspace."""
    url = f"{PBI_API}/groups/{WORKSPACE_ID}/datasets"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        datasets = response.json().get("value", [])
        print(f"Found {len(datasets)} datasets:")
        for d in datasets:
            print(f"  Name: {d['name']}")
            print(f"  ID:   {d['id']}")
            print()
    else:
        print(f"Failed: {response.status_code} {response.text}")
if __name__ == "__main__":
    token = get_access_token()
    list_datasets(token)
