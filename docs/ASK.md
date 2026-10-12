# Ask OncoGraph: source-backed questions and optional local LLM

The [public question interface](https://inoue0426.github.io/OncoGraph/#ask) matches literal entity names/identifiers in a bounded published snapshot. It lists connected relationships and up to three underlying source records per relationship (12 relationships maximum). It does **not** synthesize a clinical answer or send the question to a model. “Copy grounded prompt” copies the question and selected records for use with a model of your choice; pasting that prompt elsewhere may disclose the question to that service.

## Optional local explanation, no API key

You can use Ollama on your own computer. The browser interface and the local bridge run on the **same loopback origin**. Nothing on GitHub Pages can invoke this bridge: it has no CORS allowance, rejects mismatched/missing Origin headers and non-loopback Host headers, and is documented to bind only `127.0.0.1`. The bridge calls only Ollama on `127.0.0.1:11434`. Do not change the bind address to a public interface.

1. Install [Ollama](https://ollama.com/) and download a compatible local model, for example `ollama pull gemma3:4b`. Model downloads use storage and local compute. A different model can be selected with `ONCOGRAPH_OLLAMA_MODEL`.
2. From the repository root, install `pip install -e .` and copy the public static data with `python scripts/download_public_snapshot.py`. This copies `search-index.json`, `relations.json` and `stats.json` into `web/data/` and verifies their format. It is a snapshot, not live source queries. Alternatively, build these files with `python scripts/build_static_site.py` after importing your own local SQLite database.
3. Run `uvicorn oncograph.local_ask:app --host 127.0.0.1 --port 8765`. Open `http://127.0.0.1:8765/` in the **same browser and computer**. Ask a question, inspect the retrieved records, then press **Explain with local Ollama** if you want a model-generated summary.

The model receives the question and the **displayed** source records only after that click. Source material is treated as untrusted input to the model; the answer is labeled model-generated and displayed separately from the source records. It can still hallucinate, follow a malicious instruction embedded in data, or misunderstand a CIViC profile. The site does not verify every model claim. Always open original source links. The local bridge does not include API keys, does not query external model services, and does not save a chat history. Ollama itself runs as a separate local process with its own settings.

## Coverage and limitations

- Matching is case-insensitive but literal. It does not reliably resolve synonyms, arbitrary phrasing, or implied concepts. A no-match result means only that this bounded snapshot and matcher did not find a literal entity reference.
- At most eight entity matches, 12 relationships, and three source items per relationship are supplied. Sorting favors relationships between two matched entities. This is **not** an exhaustive retrieval or a validated retrieval benchmark.
- CIViC evidence direction, resistance, and contradictions are retained in the displayed records. FDA labels and CIViC Assertions are not integrated. A gene path, trial record, or approved-stage indication is not itself a US approval or treatment recommendation.
- Browser permission policies for a public site calling `localhost` differ across browsers. This design serves the optional model interface from localhost to avoid that dependency. GitHub Pages remains a free, static evidence viewer and prompt exporter.
