# Setting Up the Power BI Connector (Optional)

By default, you copy generated measures into your Power BI model manually via Tabular Editor. The Power BI connector lets the agent push them in automatically using the Power BI REST API.

> **Do you need this?** Most users do not. It is useful if you are generating many measures and want to avoid the copy-paste step. If you are just getting started, skip this and come back later.

---

## What you need

- An **Azure account** with access to the same tenant as your Power BI workspace
- A **Power BI Pro or Premium** licence

---

## Step 1 — Register an app in Azure

1. Go to [portal.azure.com](https://portal.azure.com) and sign in
2. In the search bar at the top, search for **Azure Active Directory** and open it
3. In the left menu, click **App registrations**, then click **New registration**
4. Give it a name (e.g. `pbi-agent`), leave everything else as default, and click **Register**
5. You are now on the app's overview page. Copy two values from here:
   - **Application (client) ID** → this will be your `PBI_CLIENT_ID`
   - **Directory (tenant) ID** → this will be your `PBI_TENANT_ID`

---

## Step 2 — Create a client secret

1. In your app registration, click **Certificates & secrets** in the left menu
2. Click **New client secret**
3. Give it a description (e.g. `pbi-agent-secret`) and choose an expiry period
4. Click **Add**
5. Copy the **Value** immediately — it is only shown once and cannot be retrieved later. This will be your `PBI_CLIENT_SECRET`

---

## Step 3 — Grant Power BI permissions

1. In your app registration, click **API permissions** in the left menu
2. Click **Add a permission**
3. Choose **Power BI Service** from the list
4. Select **Delegated permissions**
5. Tick **Dataset.ReadWrite.All** and click **Add permissions**
6. Click **Grant admin consent for [your organisation]** and confirm

> If you do not see the Grant admin consent button, you will need to ask your Azure administrator to do this step.

---

## Step 4 — Find your Workspace ID and Dataset ID

1. Open [app.powerbi.com](https://app.powerbi.com) in your browser
2. Navigate to your dataset
3. Look at the URL in your browser's address bar — it will look like this:

```
https://app.powerbi.com/groups/WORKSPACE_ID/datasets/DATASET_ID/details
```

Copy both IDs from the URL.

---

## Step 5 — Update your .env file

Open the `.env` file in the `pbi-agent` folder (in Notepad or any text editor) and add these five lines:

```
PBI_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PBI_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PBI_CLIENT_SECRET=your~secret~value
PBI_WORKSPACE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PBI_DATASET_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Replace each placeholder with the values you copied in Steps 1–4.

---

## Step 6 — Test the connection

In your terminal (inside the `pbi-agent` folder), run:

```
python pbi_connector.py
```

If everything is set up correctly, it will print a list of the datasets available in your workspace.

---

## Troubleshooting

**"401 Unauthorized" error**
This usually means admin consent was not granted (Step 3) or your client secret has expired. Check both.

**No datasets listed**
Make sure `PBI_WORKSPACE_ID` is correct and that your account has access to that workspace in Power BI.
