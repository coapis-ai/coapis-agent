# FAQ

## Is this the same as OpenClaw's built-in browser tool?

No. OpenClaw's built-in `browser` tool uses a snapshot→act loop where the agent reads the DOM, picks an element by ref, and acts on it one step at a time. It's great for simple tasks but breaks on complex multi-step workflows.

**Browser-Use** is a dedicated browser AI agent — it sees screenshots, reasons about the page, and executes entire workflows autonomously. Think of it as the difference between "manual gear" and "self-driving."

## Does it cost money?

Yes — each step calls an external LLM (e.g., GPT-4o-mini). A typical 20-step task ≈ 20 API calls. That's why the skill recommends using the **free** built-in tool for simple tasks and only switching to Browser-Use for complex workflows.

## Can I use it without an API key?

No. Browser-Use needs an LLM to make decisions. You need any OpenAI-compatible API key (OpenAI, Azure, or third-party providers).

## Is it safe to use with my real Chrome?

Mode B connects to your real Chrome, so:
- ✅ It can see your cookies, tabs, bookmarks — but only interacts with pages as instructed
- ⚠️ Use `allowed_domains` to restrict where it can navigate
- ⚠️ Use `sensitive_data` instead of putting passwords in the task

## Which LLM should I use?

| Model | Speed | Quality | Cost |
|-------|:---:|:---:|:---:|
| gpt-4o-mini | ⚡ Fast | Good | 💰 Cheap |
| gpt-4o | Medium | Best | 💰💰 |
| claude-sonnet | Medium | Great | 💰💰 |
| gemini | — | ❌ Incompatible | — |

**Recommendation:** Start with `gpt-4o-mini` for most tasks. Switch to `gpt-4o` only if the task requires better reasoning.

## Can I run it headless (no visible browser)?

Yes, for Mode A:
```python
browser = Browser(headless=True)
```
Mode B always shows the browser (it's your real Chrome).
