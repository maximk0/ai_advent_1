# Instructions for AI Agents

## About the Project

This is a single educational AI Advent project that gradually brings the results of different daily assignments together in one application. It includes a web chat, document RAG, conversation memory, model settings, comparison/demo modes, project help, and other learning features. Do not treat it as a collection of unrelated daily apps. Before making changes, check `README.md` and the relevant modules.

Main parts of the current application:

- `main.py` is the stable entry point for the current web application and HTTP API. Keep it independent of the current assignment day.
- `chat_ui.py` contains the web chat, sidebar, and tabs.
- `simple_agent.py` handles conversations, models, RAG, memory, and sources.
- `project_rag.py` and the generated `project_index.json` provide search over this project's documentation and code.
- `document_indexer.py`, `document_index.json`, and `docs/` are used for the educational RAG index and knowledge base.
- `mcp_client.py` and `mcp_server_git.py` provide the current Git MCP integration.
- Older assignment results live in Git history; the working tree should contain the current app and only modules it uses.

## Preserve Existing Functionality

- Do not replace the entire interface when changing one feature or tab.
- Preserve the main chat, sidebar, model selection, settings, conversation controls, RAG, and sources unless the task explicitly asks to change them.
- Before changing the interface, check how its components connect to the API and application state.
- Do not remove learning scenarios, documents, settings, or files from previous days unless explicitly asked.
- The user prefers a clear web interface; the code is kept in the repository for submission.
- The user is open to suggestions that improve usability, performance, reliability, or other aspects of the project. When you see a useful opportunity, explain its benefit briefly and suggest an option; do not assume the current implementation is the only possible approach.
- Preserve working features and make substantial changes in line with the current task and the user's preferences.

## Assignment Organization

Keep one evolving application at `main.py`, rather than creating a new `dayNN.py` entry point for each assignment. Update the README and project guide when the current app's behavior or launch steps change. Earlier assignment results are preserved in Git history. The app currently uses port `8030`.

## Running the Application

Run the current primary application from the project root:

```bash
python3 main.py
```

Open `http://127.0.0.1:8030`.

The local LLM is optional for normal use. The user starts it manually only when they need it or are recording a video, because it places a significant load on the laptop. Do not start the local model automatically or assume that `llama-server` is running. If the model is unavailable, keep the application usable with other available modes where possible.

For access from a phone on the home network, configure network binding and protect the service. Do not expose this educational HTTP service directly to the public internet without TLS and appropriate security measures.

## Models and Secrets

- Cloud models use a provider API key; the local Qwen model is served through `llama-server`.
- Never put API keys, passwords, tokens, or personal data in source code, documentation, example commands, or Git.
- Pass secrets through environment variables or the application's intended input fields.
- Do not claim that a cloud model is free or available without checking the provider's current terms.

## Knowledge Bases and Indexes

- `docs/` contains the intentionally fictional “Sova-17” knowledge base used to demonstrate RAG. Do not replace it with project documentation unless explicitly asked.
- `document_index.json` and `project_index.json` are generated indexes. If source documents or indexing logic change, check whether the relevant index needs to be rebuilt.
- Preserve clear source filenames, section names, and chunk IDs for RAG results when the relevant screen displays them.
- Do not include `.env`, chat history, caches, virtual environments, or other secret or generated operational data in an index.

## Making Changes

- Locate the existing handler or component first and make the smallest coherent change.
- Preserve compatibility with existing APIs and saved settings, or update all dependent code explicitly.
- After changing Python files, check the syntax of the affected modules. For interface changes, check embedded JavaScript syntax when practical.
- Avoid long cloud model requests and unnecessary API charges.
- If the environment cannot reach a local server, report that limitation and do not claim the check succeeded.
- In the final response, briefly summarize the changes and list the checks performed and their results.

## Documentation

Update `README.md` when startup steps, the interface, API, environment variables, or significant limitations change. Keep this file focused on short-lived agent instructions; put detailed user workflows in the README.
