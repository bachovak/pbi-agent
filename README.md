# Power BI DAX Agent

An AI-powered tool that generates, validates, and manages DAX measures for Power BI models using Claude. Describe the measure you need in plain English — the agent generates DAX, validates it structurally and semantically, and saves approved measures to a reusable library.

## Features

- **Natural language to DAX** — describe what you want, get valid DAX back
- **Dual validation** — structural check (syntax) + semantic check (does it answer the request?)
- **Self-correcting** — retries up to 3 times with its own feedback if validation fails
- **Duplicate detection** — flags if a similar measure already exists in the library
- **Measure library** — approved measures are saved and searchable
- **Model-aware** — reads your `Model.bim` so it only uses tables and columns that actually exist
- **Model sanitisation** — scans your model file for sensitive data before loading; nothing leaves your machine until you approve
- **Two interfaces** — Streamlit web UI or CLI

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Also install Streamlit if you want the web UI:

```bash
pip install streamlit
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
# Required
ANTHROPIC_API_KEY=your_anthropic_api_key

# Path to your Power BI model.bim file
BIM_PATH=C:\path\to\your\Model.bim

# Optional — only needed if using pbi_connector.py to push measures via the Power BI REST API
PBI_CLIENT_ID=your_azure_app_client_id
PBI_TENANT_ID=your_azure_tenant_id
PBI_CLIENT_SECRET=your_azure_client_secret
PBI_WORKSPACE_ID=your_powerbi_workspace_id
PBI_DATASET_ID=your_powerbi_dataset_id
```

Get your Anthropic API key at [console.anthropic.com](https://console.anthropic.com).

### 3. Get your model.bim file

Export it from Tabular Editor: **File → Save As** and save as `Model.bim`. Point `BIM_PATH` in your `.env` to this file.

---

## Usage

### Streamlit web UI (recommended)

```bash
streamlit run app.py
```

Opens in your browser. Paste your `Model.bim` path in the sidebar, configure sanitisation options, and click **Load Model**. The sanitiser scans the file locally and shows you a review screen — no data leaves your machine at this point. Click **Approve and Load Model** to proceed. Then type your measure request and click **Generate DAX**. Review the output and click **Approve & Save** to add it to the library.

### CLI agent (full, model-aware)

```bash
python dax_agent.py
```

Same logic as the web UI but runs in the terminal. Reads your `BIM_PATH` model, checks for duplicates, generates and validates DAX, then saves approved measures.

### CLI agent (simple, no model context)

```bash
python hello_agent.py
```

A simpler version that generates DAX without reading your model file. Useful for quick one-off measures when you don't need model-aware validation.

### Inspect your model

```bash
python model_inspector.py
```

Prints a structured summary of your model's tables, columns, and existing measures. Useful for verifying the agent can see your model correctly.

### View saved measures

```bash
python show_library.py
```

Lists all measures saved in the library with their IDs and descriptions.

### Build a lineage graph

```bash
python lineage.py
```

Parses your `Model.bim` and builds a dependency graph (`lineage.json`) showing which measures reference which columns and tables. Also prints an impact analysis showing what would break if a column were removed.

---

## Pushing measures to Power BI (optional)

`pbi_connector.py` connects to the Power BI REST API to push measures directly to a dataset. Requires an Azure AD app registration with Power BI permissions and the `PBI_*` env variables set.

```bash
python pbi_connector.py
```

This is optional — you can also copy generated DAX manually into Tabular Editor.

---

## File overview

| File | Purpose |
|---|---|
| `app.py` | Streamlit web UI |
| `sanitiser.py` | Model sanitisation module (called by `app.py`) |
| `dax_agent.py` | Full CLI agent (model-aware, with library) |
| `hello_agent.py` | Simple CLI agent (no model context) |
| `model_inspector.py` | Reads and prints your model schema |
| `lineage.py` | Builds measure/column dependency graph |
| `show_library.py` | Lists saved measures |
| `pbi_connector.py` | Pushes measures to Power BI via REST API |
| `requirements.txt` | Python dependencies |

## Local data files (not in repo)

These files are generated locally and excluded from git:

| File | Purpose |
|---|---|
| `Model.bim` | Your Power BI model (export from Tabular Editor) |
| `measure_library.json` | Saved measures (auto-created on first approval) |
| `lineage.json` | Dependency graph (auto-created by `lineage.py`) |
