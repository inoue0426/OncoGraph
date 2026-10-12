# Ask OncoGraph: source-backed questions and optional local LLM

The [public question interface](https://inoue0426.github.io/OncoGraph/#ask) matches literal entity names/identifiers in a bounded published snapshot. It lists connected relationships and up to three underlying source records per relationship (12 relationships maximum). It does **not** synthesize a clinical answer or send the question to a model. “Copy grounded prompt” copies the question and selected records for use with a model of your choice; pasting that prompt elsewhere may disclose the question to that service.

## Optional local explanation, no API key

You can use Ollama on your own computer. The browser interface and the bridge run on the **same origin**. GitHub Pages cannot call the bridge across origins: it has no CORS allowance and rejects mismatched/missing Origin headers. The default bridge accepts only loopback Host headers. The bridge calls only Ollama on `127.0.0.1:11434`. Keep both services bound to loopback.

1. Install [Ollama](https://ollama.com/) and download a compatible local model, for example `ollama pull gemma3:4b`. Model downloads use storage and local compute. A different model can be selected with `ONCOGRAPH_OLLAMA_MODEL`.
2. From the repository root, install `pip install -e .` and copy the public static data with `python scripts/download_public_snapshot.py`. This copies `search-index.json`, `relations.json` and `stats.json` into `web/data/` and verifies their format. It is a snapshot, not live source queries. Alternatively, build these files with `python scripts/build_static_site.py` after importing your own local SQLite database.
3. Run `uvicorn oncograph.local_ask:app --host 127.0.0.1 --port 8765`. Open `http://127.0.0.1:8765/` in the **same browser and computer**. Ask a question, inspect the retrieved records, then press **Explain with Ollama on this server** if you want a model-generated summary.

The model receives the question and the **displayed** source records only after that click. Source material is treated as untrusted input to the model; the answer is labeled model-generated and displayed separately from the source records. It can still hallucinate, follow a malicious instruction embedded in data, or misunderstand a CIViC profile. The site does not verify every model claim. Always open original source links. The local bridge does not include API keys, does not query external model services, and does not save a chat history. Ollama itself runs as a separate local process with its own settings.

## Temporary public demo from a Windows machine

This is an **anonymous, temporary test URL**. No router port or Windows inbound firewall rule is needed: Cloudflare Tunnel makes an outbound connection and forwards only the OncoGraph app. **Never tunnel port 11434 or bind Ollama to `0.0.0.0`.** Quick Tunnels have no uptime guarantee and the URL changes each time. Anyone with the URL can use the app; this is not an authenticated production service.

1. On Windows, install Python 3.11+ and [Ollama for Windows](https://ollama.com/download/windows). Run `ollama pull gemma3:4b`. Install the official [cloudflared Windows download](https://developers.cloudflare.com/tunnel/downloads/). Check `python --version`, `git --version`, and `cloudflared --version` in a new terminal window. Clone this repository into your user directory; do not run the repository commands from `C:\Windows\System32`:

   ```bat
   cd /d "%USERPROFILE%"
   git clone https://github.com/inoue0426/OncoGraph.git
   cd OncoGraph
   ```

   If you already cloned the repository, go to that existing directory and run `git pull` instead.
2. Run `python -m pip install -e .` and `python scripts\download_public_snapshot.py` once. Confirm `web\data\search-index.json` and `web\data\relations.json` exist. Repeat the download when you want to refresh the local copy; the public site can itself lag upstream data.
3. In terminal window A, start the bounded server. Use the commands for your shell:

   ```powershell
   $env:ONCOGRAPH_PUBLIC_MODE = "1"
   python -m uvicorn oncograph.local_ask:app --host 127.0.0.1 --port 8765 --workers 1 --no-access-log
   ```

   Command Prompt (`cmd.exe`):

   ```bat
   set "ONCOGRAPH_PUBLIC_MODE=1"
   python -m uvicorn oncograph.local_ask:app --host 127.0.0.1 --port 8765 --workers 1 --no-access-log
   ```

4. In terminal window B, start the tunnel (same command in PowerShell or Command Prompt):

   ```powershell
   cloudflared tunnel --url http://127.0.0.1:8765
   ```

5. Share the generated `https://<random>.trycloudflare.com/` URL. Visitors can paste it into [the hosted Q&A entry on GitHub Pages](https://inoue0426.github.io/OncoGraph/#ask), or open it directly. Their browser loads the OncoGraph site through the tunnel; only after they press **Explain with Ollama on this server** does the question reach the Windows model. Stop window B to take the public URL offline.

Public mode accepts only same-origin HTTPS requests on a `*.trycloudflare.com` hostname (or a separately configured exact `ONCOGRAPH_PUBLIC_HOST`), requires a Cloudflare client IP header, limits the API to **three requests per IP per hour and 60 total requests per 24 hours**, and permits one active generation. The limits live in memory and reset when the server restarts. They reduce accidental overload; **they do not prevent distributed abuse, denial of service, or all prompt-injection attacks**. Do not enter patient-identifying information. To run a persistent public service, use a stable hostname and configure edge authentication or abuse controls separately. An unauthenticated permanent deployment needs additional security review.

## Coverage and limitations

- Matching is case-insensitive but literal. It does not reliably resolve synonyms, arbitrary phrasing, or implied concepts. A no-match result means only that this bounded snapshot and matcher did not find a literal entity reference.
- At most eight entity matches, 12 relationships, and three source items per relationship are supplied. Sorting favors relationships between two matched entities. This is **not** an exhaustive retrieval or a validated retrieval benchmark.
- CIViC evidence direction, resistance, and contradictions are retained in the displayed records. FDA labels and CIViC Assertions are not integrated. A gene path, trial record, or approved-stage indication is not itself a US approval or treatment recommendation.
- Browser permission policies for a public site calling `localhost` differ across browsers. The Pages site opens the separately hosted UI instead of fetching its API across origins. Pages remains a free, static evidence viewer and prompt exporter.
