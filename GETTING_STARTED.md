# Getting Started with Power BI DAX Agent

This guide takes you from zero to running the agent on your own Power BI model.

---

## What you need before starting

- Python 3.9 or higher — [download here](https://www.python.org/downloads/)
- Git — [download here](https://git-scm.com/downloads)
- An Anthropic account — [sign up here](https://console.anthropic.com)
- Your Power BI model file (`Model.bim`) exported from Tabular Editor

---

## Step 1 — Clone the repository

Open a terminal and run:

```bash
git clone https://github.com/bachovak/pbi-agent.git
cd pbi-agent
```

---

## Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

If you want to use the web UI (recommended), also install Streamlit:

```bash
pip install streamlit
```

---

## Step 3 — Get your Anthropic API key

The agent uses Claude to generate and validate DAX. You need an API key.

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign in or create an account
3. Click **API Keys** in the left sidebar
4. Click **Create Key**, give it a name (e.g. `pbi-agent`), and copy the key

> Keep this key private — treat it like a password. Never commit it to git.

---

## Step 4 — Export your model.bim file

The agent reads your Power BI data model to generate DAX that uses only your actual tables and columns.

1. Open your Power BI report in **Tabular Editor** (free at [tabulareditor.com](https://tabulareditor.com))
2. Go to **File → Save As**
3. Save the file as `Model.bim` somewhere on your machine (e.g. `C:\Documents\MyProject\Model.bim`)

---

## Step 5 — Create your .env file

In the project folder, copy the example file:

**On Windows:**
```bash
copy .env.example .env
```

**On Mac/Linux:**
```bash
cp .env.example .env
```

Then open `.env` in any text editor and fill in your values:

```env
ANTHROPIC_API_KEY=sk-ant-...        ← paste your key from Step 3
BIM_PATH=C:\Documents\MyProject\Model.bim   ← path to your model from Step 4
```

The Power BI connector variables (`PBI_CLIENT_ID` etc.) are **optional** — only needed if you want to push measures directly to Power BI. See [Configuring the Power BI connector](#configuring-the-power-bi-connector-optional) below.

---

## Step 6 — Run the agent

### Option A: Web UI (recommended)

```bash
streamlit run app.py
```

Your browser will open automatically at `http://localhost:8501`.

**How to use it:**

1. Paste the path to your `Model.bim` file in the sidebar (or leave it as the default from `BIM_PATH`)
2. Choose your sanitisation settings — by default the tool will mask SQL connection strings, file paths, URLs, and email addresses before the model is loaded. You can also optionally mask GUIDs, remove RLS role definitions, and strip developer comments
3. Click **Load Model** — the file is scanned locally on your machine; nothing is sent anywhere at this point
4. A **Sanitisation Review** screen appears showing exactly what was found and redacted. If the model is clean, it will say so. Review the list and click **Approve and Load Model** to proceed, or **Cancel** to go back
5. The model loads and the **lineage graph is built automatically** in the background. You will see a Lineage section in the sidebar showing node and edge counts. Scroll down on the main page to find **Impact Analysis** — select any table, column, or measure to see everything that depends on it before making a change
6. Type your measure request in plain English, e.g.:
   - `total room revenue for the current year`
   - `average daily rate by room type`
   - `number of bookings this month`
7. Click **Generate DAX**
8. The agent checks your library for duplicates, then generates and validates the DAX
9. Review the output — click **Approve & Save** to add it to your library, or **Reject** to try again

### Option B: Command line

```bash
python dax_agent.py
```

Same logic as the web UI but in your terminal. Type your request when prompted, and the agent will print the validated DAX.

---

## Useful scripts

### View your saved measures

```bash
python show_library.py
```

Lists all measures you have approved and saved to the library.

### Inspect your model

```bash
python model_inspector.py
```

Prints a full summary of tables, columns, and existing measures from your `Model.bim`. Run this first if you are unsure whether the agent can see your model correctly.

### Build a lineage graph (CLI)

```bash
python lineage.py
```

Analyses your model and generates a `lineage.json` file showing which measures depend on which columns and tables. Also prints an impact report — useful for understanding what breaks if you rename or remove a column.

> In the web UI this happens automatically — no need to run this script separately unless you want the `lineage.json` file saved to disk.

---

## Configuring the Power BI connector (optional)

`pbi_connector.py` lets you push generated measures directly into your Power BI dataset via the REST API, instead of copying them manually into Tabular Editor.

### What you need

- An Azure account with access to the same tenant as your Power BI workspace
- Power BI Pro or Premium licence

### Steps

**1. Register an app in Azure**

1. Go to [portal.azure.com](https://portal.azure.com)
2. Search for **Azure Active Directory** and open it
3. Click **App registrations → New registration**
4. Give it a name (e.g. `pbi-agent`), leave the rest as default, click **Register**
5. Copy the **Application (client) ID** — this is your `PBI_CLIENT_ID`
6. Copy the **Directory (tenant) ID** — this is your `PBI_TENANT_ID`

**2. Create a client secret**

1. In your app registration, go to **Certificates & secrets**
2. Click **New client secret**, give it a description and expiry
3. Copy the **Value** immediately (it is only shown once) — this is your `PBI_CLIENT_SECRET`

**3. Grant Power BI permissions**

1. In your app registration, go to **API permissions → Add a permission**
2. Choose **Power BI Service**
3. Select **Delegated permissions** and add:
   - `Dataset.ReadWrite.All`
4. Click **Grant admin consent**

**4. Find your Workspace ID and Dataset ID**

Open Power BI in your browser and navigate to your dataset. The URL will look like:

```
https://app.powerbi.com/groups/<WORKSPACE_ID>/datasets/<DATASET_ID>/details
```

Copy both IDs into your `.env` file.

**5. Update your .env**

```env
PBI_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PBI_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PBI_CLIENT_SECRET=your~secret~value
PBI_WORKSPACE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PBI_DATASET_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

**6. Test the connection**

```bash
python pbi_connector.py
```

If configured correctly, it will print the datasets available in your workspace.

---

## Troubleshooting

**`ANTHROPIC_API_KEY not found` or authentication error**
Make sure your `.env` file is in the project root folder (same folder as `app.py`) and the key is correctly pasted with no extra spaces. If you cloned the repo, the `.env` file is not included — copy `.env.example` to `.env` and fill in your values.

**`Failed to parse sanitised model` error after approving**
This should not happen with a valid `Model.bim` file. If it does, try turning off the **Remove developer comments** toggle and loading again — some non-standard files may contain comment-like patterns in unexpected places.

**`Cannot find model file` or model not loading**
Check that `BIM_PATH` in your `.env` points to the exact location of your `Model.bim` file. On Windows, use either forward slashes (`C:/path/to/Model.bim`) or escaped backslashes (`C:\\path\\to\\Model.bim`).

**DAX keeps failing validation**
Try rephrasing your request with more specific table and column names. You can run `python model_inspector.py` to see exactly what table and column names are in your model, then reference them directly in your request.

**Streamlit command not found**
Run `pip install streamlit` and try again.

**Power BI connector returns 401 Unauthorized**
Check that admin consent was granted for your API permissions in Azure, and that your client secret has not expired.
