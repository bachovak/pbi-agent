# Getting Started with Power BI DAX Agent

This guide walks you through setting up the agent step by step. No programming experience is required — just follow each step in order.

---

## Before you begin — what you will need

You will need to install two small programs and create one online account before you can start. Here is the full list:

| What | Why you need it | Where to get it |
|---|---|---|
| **Python** | The language the agent is written in | [python.org/downloads](https://www.python.org/downloads/) |
| **Git** | Downloads the project files to your computer | [git-scm.com/downloads](https://git-scm.com/downloads) |
| **Anthropic account** | The agent uses Claude (AI) to generate DAX — you need an API key | [console.anthropic.com](https://console.anthropic.com) |
| **Your Power BI model file** | The agent reads this to understand your tables and columns | Exported from Tabular Editor — see Step 4 |

> **Not sure if Python or Git is already installed?**
> Open a terminal (see the tip below) and type `python --version` then press Enter. If you see a version number like `Python 3.11.2`, it is already installed. Do the same with `git --version`.

---

### How to open a terminal

A terminal is a text window where you type commands. Here is how to open one:

- **Windows:** Press the Windows key, type `cmd`, and press Enter. A black window will appear.
- **Mac:** Press Cmd + Space, type `Terminal`, and press Enter.

You will use this window throughout this guide. Keep it open.

---

## Step 1 — Install Python

1. Go to [python.org/downloads](https://www.python.org/downloads/) and click the big **Download Python** button
2. Run the installer
3. **Important (Windows only):** On the first screen of the installer, tick the box that says **"Add Python to PATH"** before clicking Install

Once installed, close and reopen your terminal, then type `python --version` to confirm it worked.

---

## Step 2 — Install Git

1. Go to [git-scm.com/downloads](https://git-scm.com/downloads) and download the installer for your system
2. Run the installer — the default options are fine, just keep clicking Next
3. Once installed, close and reopen your terminal, then type `git --version` to confirm it worked

---

## Step 3 — Download the project

In your terminal, type the following two commands one at a time, pressing Enter after each:

```
git clone https://github.com/bachovak/pbi-agent.git
```

```
cd pbi-agent
```

The first command downloads all the project files into a new folder called `pbi-agent` on your computer. The second command moves your terminal into that folder.

> **Where is the folder?** It will be created in whatever folder your terminal was pointing to when you ran the command. On Windows this is usually `C:\Users\YourName\pbi-agent`.

---

## Step 4 — Install the required packages

Still in your terminal (make sure you are inside the `pbi-agent` folder), run:

```
pip install -r requirements.txt
```

Then run:

```
pip install streamlit
```

This downloads all the small pieces of software the agent depends on. It may take a minute or two.

> **What is pip?** It is Python's built-in tool for installing packages. It was installed automatically with Python.

---

## Step 5 — Get your Anthropic API key

The agent uses Claude (an AI made by Anthropic) to generate and check your DAX. You need an API key — think of it as a password that lets the agent talk to Claude on your behalf.

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in (or create a free account)
2. In the left sidebar, click **API Keys**
3. Click **Create Key**, give it a name like `pbi-agent`, and click Create
4. A long string starting with `sk-ant-` will appear — **copy it now** (it will not be shown again)

> **Keep this key private.** Do not share it or paste it into emails. Treat it like a password.

---

## Step 6 — Export your Power BI model file

The agent needs a copy of your data model so it knows what tables and columns you have. You export this from Tabular Editor.

1. Download and install **Tabular Editor 2** (free) from [tabulareditor.com](https://tabulareditor.com) if you do not already have it
2. Open your Power BI report, then open Tabular Editor from the **External Tools** ribbon
3. In Tabular Editor, go to **File → Save As**
4. Save the file as `Model.bim` somewhere easy to find, for example:
   `C:\Users\YourName\Documents\MyProject\Model.bim`

> Make a note of the full file path — you will need it in the next step.

---

## Step 7 — Create your settings file

The agent reads its settings from a file called `.env` in the project folder. You will create this from the provided template.

**On Windows**, in your terminal run:
```
copy .env.example .env
```

**On Mac/Linux**, run:
```
cp .env.example .env
```

Now open the `.env` file in a text editor:

- **Windows:** Open File Explorer, navigate to the `pbi-agent` folder, right-click `.env`, and choose **Open with → Notepad**
- **Mac:** Open Finder, navigate to the `pbi-agent` folder, right-click `.env`, and choose **Open with → TextEdit**

> **Can't see the file?** Files starting with a dot are hidden by default. On Windows, in File Explorer go to **View → Show → Hidden items**. On Mac, press Cmd + Shift + . in Finder.

You will see two lines to fill in. Replace the placeholder text with your actual values:

```
ANTHROPIC_API_KEY=sk-ant-...your key from Step 5...
BIM_PATH=C:\Users\YourName\Documents\MyProject\Model.bim
```

- For `BIM_PATH`, paste the full path to the `Model.bim` file you saved in Step 6
- On Windows you can use either forward slashes (`C:/Users/...`) or double backslashes (`C:\\Users\\...`) — both work

Save the file and close it.

---

## Step 8 — Run the agent

In your terminal (make sure you are in the `pbi-agent` folder), run:

```
streamlit run app.py
```

Your browser will open automatically and show the agent's interface. If it does not open, copy the address shown in the terminal (something like `http://localhost:8501`) and paste it into your browser.

---

## How to use the agent

Once the browser is open:

1. **Load your model** — the path from your `.env` file will already be filled in on the left. Click **Load Model**
2. **Review the sanitisation report** — the agent scans your model and masks any sensitive information (connection strings, email addresses, etc.) before anything is sent to Claude. A screen will show you exactly what was found. Click **Approve and Load Model** to continue
3. **Ask for a measure** — type your request in plain English in the main box, for example:
   - `total revenue for the current year`
   - `average daily rate by room type`
   - `number of bookings this month`
4. Click **Generate DAX**
5. **If a similar measure already exists** — the agent will show the existing DAX and ask what you want to do. Click **Use existing measure** to keep it, or **Generate new measure anyway** to create a new one
6. **Watch the agent log** — an expanded log shows each validation step in real time:
   - `Structural + reference validation passed.` — all column and measure references exist in your model
   - `Warning: SEMANTIC WARNING: ...` — the agent noticed something that might be wrong (e.g. aggregating a date or key column) but still proceeded
   - `Reference correction 1/2: ...` — a bad reference was found and a targeted correction was sent back to Claude
   - `Semantic: PASS` — Claude's reviewer confirmed the DAX answers your request correctly
7. Review the generated DAX, then click **Approve & Save** to add it to your library, or **Reject** to try again with a different request

---

## Helpful extras

### See all your saved measures

```
python show_library.py
```

Lists every measure you have approved and saved.

### Check what the agent can see in your model

```
python model_inspector.py
```

Prints a summary of all tables, columns, and existing measures. Run this if a generated measure seems to be using wrong names — it will show you the exact names the agent works with.

---

## Something went wrong?

**"ANTHROPIC_API_KEY not found" or login error**
Open your `.env` file and check that the key is pasted correctly with no extra spaces, and that the file is in the `pbi-agent` folder (the same folder as `app.py`).

**"Cannot find model file" or model not loading**
Check that the path in `BIM_PATH` matches exactly where you saved your `Model.bim` file. Copy the path directly from File Explorer to avoid typos.

**"Streamlit command not found"**
Run `pip install streamlit` and try again.

**"DAX keeps failing validation"**
Try being more specific in your request. Run `python model_inspector.py` to see the exact table and column names in your model, then use those names directly in your request.

**"The agent says the column doesn't exist and won't generate DAX"**
The column you asked for genuinely does not exist in your model. Run `python model_inspector.py` to see what columns are available, then rephrase your request using a column name that appears in the list.

**"I see a SEMANTIC WARNING about a date or key column in the log"**
This is a non-blocking warning — the measure was still generated and validated. It means the DAX is directly aggregating a column that is not designed to be summed (such as a date key or ID). Review the generated DAX carefully before approving it.

**"Failed to parse sanitised model" after approving**
Turn off the **Remove developer comments** toggle in the sanitisation screen and try loading again.

---

## Optional: push measures directly to Power BI

By default, you copy generated measures into your Power BI model manually via Tabular Editor. If you would prefer the agent to push them in automatically, you can set up the Power BI connector — see [CONNECTOR_SETUP.md](CONNECTOR_SETUP.md) for instructions.

> This requires an Azure account and a Power BI Pro or Premium licence. Most users will not need it.
>
> **Note:** this feature has not been tested, so it is unclear whether it works as expected. Use at your own risk. If you do try it, any feedback on how it works (or doesn't) would be very welcome.
