# Mode A vs Mode B

## Mode A: Built-in Chromium

Browser-Use launches its own Chromium browser.

```python
browser = Browser(headless=False, user_data_dir="~/.browser-use/my-profile")
```

**Pros:**
- Zero setup, works immediately
- `user_data_dir` persists login sessions

**Cons:**
- Sites can detect `navigator.webdriver=true`
- Reddit, LinkedIn, etc. may block automation

**Best for:** Internal tools, simple scraping, testing

---

## Mode B: Connect to Real Chrome ✅ Recommended

Browser-Use connects to your existing Chrome via CDP (Chrome DevTools Protocol).

```python
browser = Browser(cdp_url="http://127.0.0.1:9222")
```

**Setup (once per session):**
```bash
# 1. Quit Chrome completely
# 2. Relaunch with debugging port:

# Mac
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &

# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222 &

# 3. Verify
curl -s http://127.0.0.1:9222/json/version
```

**Pros:**
- Completely undetectable — it's your real browser
- Uses your existing cookies/logins
- No anti-bot issues

**Cons:**
- Requires Chrome restart with debug flag
- Shares your real browser session

**Best for:** Social media posting, anything with login, anti-bot sites

---

## Decision Flowchart

```
Need to interact with a site that detects bots?
  YES → Mode B (Real Chrome)
  NO  → Does the task need existing login cookies?
          YES → Mode B
          NO  → Mode A (simpler setup)
```
