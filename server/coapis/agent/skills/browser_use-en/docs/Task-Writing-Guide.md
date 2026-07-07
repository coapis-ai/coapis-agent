# Task Writing Guide

The **task prompt** is the most important factor in Browser-Use success. A well-written task completes in one run; a vague one wastes steps and fails.

## ✅ Good: Specific Step-by-Step

```python
task = """
1. Go to https://www.reddit.com/login
2. Enter username: x_user
3. Enter password: x_pass
4. Click the login button
5. If CAPTCHA appears, wait 30 seconds for manual completion
6. Navigate to https://www.reddit.com/r/python/submit
7. Enter title: "My Amazing Post"
8. Enter body: "This is the content..."
9. Click the Post button
10. Return the URL of the posted page
"""
```

## ❌ Bad: Vague and Open-Ended

```python
task = "Post something on Reddit"
# AI doesn't know: which subreddit? what content? login first?
```

## Pro Tips

### 1. Name Actions Explicitly
```python
task = """
Use send_keys with "Tab Tab Enter" if the submit button can't be clicked
"""
```

### 2. Add Error Recovery
```python
task = """
If the page fails to load, refresh and wait 5 seconds.
If the element is not found, scroll down and look again.
"""
```

### 3. Handle CAPTCHA
```python
task = """
If you encounter a CAPTCHA or "I'm not a robot" checkbox,
wait 30 seconds for the user to complete it manually, then continue.
"""
```

### 4. Be Explicit About Output
```python
task = """
Extract the top 5 results and return them as:
- Title: ...
- URL: ...
- Price: ...
"""
```

### 5. Use `extend_system_message` for Recurring Rules
```python
agent = Agent(
    task="...",
    extend_system_message="Always close cookie banners before interacting with the page.",
    ...
)
```
