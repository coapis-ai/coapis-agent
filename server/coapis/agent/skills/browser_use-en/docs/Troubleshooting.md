# Troubleshooting

## Site Detects Automation

**Symptom:** Site shows "automated browser detected" or silently blocks actions.

**Fix:** Switch to Mode B (Real Chrome):
```python
browser = Browser(cdp_url="http://127.0.0.1:9222")
```
See [[Mode A vs Mode B]] for setup instructions.

---

## CAPTCHA / reCAPTCHA Appears

**Symptom:** Human verification popup blocks the workflow.

**Fix:** Add wait time in your task:
```python
task = "... If CAPTCHA appears, wait 30 seconds for manual completion, then continue."
```
The user completes the CAPTCHA on their screen while Browser-Use waits.

---

## LLM Timeout

**Symptom:** `LLM request timed out` error.

**Fix options:**
1. Set a `fallback_llm`:
```python
agent = Agent(
    llm=primary_llm,
    fallback_llm=ChatOpenAI(model="gpt-4o-mini", ...),
    ...
)
```
2. Increase timeout: `llm_timeout=120`
3. Use a faster model (gpt-4o-mini vs gpt-4o)

---

## Action Completed But Nothing Happened

**Symptom:** Browser-Use says "posted successfully" but the post doesn't exist.

**Causes:**
1. Anti-spam filter (new accounts on Reddit, Twitter, etc.)
2. The "submit" click didn't actually register

**Fix:**
- Add verification step in task: `"After posting, verify the post appears on the page"`
- For new accounts: build karma/history first before automated posting

---

## Gemini LLM Doesn't Work

**Symptom:** Structured output errors with Gemini models.

**Cause:** Gemini's JSON Schema format is incompatible with Browser-Use's structured output.

**Fix:** Use GPT-4o-mini or Claude instead. This is a known limitation.

---

## Chrome Won't Connect (Mode B)

**Symptom:** `Connection refused` on port 9222.

**Checklist:**
1. Did you fully quit Chrome before relaunching? (Check Activity Monitor / Task Manager)
2. Is the `--remote-debugging-port=9222` flag present?
3. Verify: `curl -s http://127.0.0.1:9222/json/version`
4. Is another process using port 9222? `lsof -i :9222`
