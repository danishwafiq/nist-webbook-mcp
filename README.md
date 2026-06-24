# NIST Chemistry WebBook MCP Server

An MCP (Model Context Protocol) server that gives Claude live access to the
[NIST Chemistry WebBook](https://webbook.nist.gov/chemistry/) — thermochemical
and thermophysical data for thousands of compounds.

---

## Tools Provided

| Tool | Description |
|---|---|
| `nist_search_compound` | Thermochemical data by name, formula, or CAS number |
| `nist_get_thermophysical` | Isobaric thermophysical properties over a T range |
| `nist_get_saturation` | Saturation curve (vapor pressure, ΔHvap, densities) |
| `nist_list_supported_fluids` | Lists all fluids with high-accuracy data |

---

## Example Prompts (once connected)

- "What is the enthalpy of formation of methane?"
- "Get thermophysical properties of water at 1 atm from 300 K to 500 K"
- "Give me the saturation curve for propane from 200 K to 360 K"
- "What are the Shomate equation coefficients for CO2?"
- "Get density and viscosity of nitrogen at 10 MPa from 200 to 600 K"

---

## Setup

### 1. Install Python dependencies

```bash
cd nist_webbook_mcp
pip install -r requirements.txt
```

### 2a. Local use — Claude Desktop (stdio)

Add to your `claude_desktop_config.json`
(on macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "nist-webbook": {
      "command": "python",
      "args": ["/FULL/PATH/TO/nist_webbook_mcp/server.py"]
    }
  }
}
```

Restart Claude Desktop. The connector will appear under the **+** menu → Connectors.

---

### 2b. Remote use — Claude.ai web connector

This makes the server accessible from claude.ai (web/mobile), not just Claude Desktop.

**Step 1 — Deploy to a free host (Railway or Render)**

**Railway (recommended — free tier available):**
1. Push this folder to a GitHub repo
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Set start command: `python server.py --http`
4. Set port: `8000`
5. Railway gives you a public URL like `https://nist-webbook-mcp-production.up.railway.app`

**Render:**
1. New → Web Service → connect GitHub repo
2. Build command: `pip install -r requirements.txt`
3. Start command: `python server.py --http`
4. Port: `8000`

**Step 2 — Add as custom connector in Claude.ai**

1. Go to [claude.ai](https://claude.ai) → Settings (bottom left) → Connectors
2. Click **Add custom connector**
3. Enter your deployed URL: `https://your-app.up.railway.app`
4. Click **Add**

**Step 3 — Enable per conversation**

Click the **+** icon at the bottom of any chat → **Connectors** → toggle on **nist-webbook**.

---

## Notes

- NIST WebBook has no official public API — this server scrapes HTML pages respectfully.
- The `nist_get_thermophysical` and `nist_get_saturation` tools work only for the ~80
  fluids listed by `nist_list_supported_fluids`. All other compounds work via
  `nist_search_compound` (thermochemical data only).
- No API key required.
- No authentication needed (NIST is a public US government database).
