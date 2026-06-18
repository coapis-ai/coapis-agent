# Sensitive Data

Never hardcode passwords in your task prompts. Browser-Use has built-in sensitive data handling.

## How It Works

1. You use **placeholders** in the task (e.g., `x_user`, `x_pass`)
2. The LLM only sees the placeholders — never the real values
3. Real values are injected **directly into form fields** after the LLM decides what to do

## Basic Usage

```python
agent = Agent(
    task="Log into example.com with username x_user and password x_pass",
    sensitive_data={
        "x_user": "real_username@email.com",
        "x_pass": "real_password123",
    },
    use_vision=False,  # Disable screenshots to prevent LLM seeing passwords
    llm=llm,
    browser=browser,
)
```

## Domain-Specific Credentials

Route credentials to specific domains only:

```python
sensitive_data = {
    "https://*.work.com": {
        "work_user": "alice@work.com",
        "work_pass": "work_password",
    },
    "https://personal.com": {
        "personal_user": "alice@gmail.com",
        "personal_pass": "personal_password",
    },
}
```

## 2FA / TOTP Support

```python
agent = Agent(
    task="Login and enter bu_2fa_code when prompted for 2FA",
    sensitive_data={
        "x_user": "myusername",
        "x_pass": "mypassword",
        "bu_2fa_code": "TOTP_SECRET_KEY",  # The secret, NOT the 6-digit code
    },
    llm=llm, browser=browser,
)
```

The placeholder name must **end with `bu_2fa_code`**. Browser-Use auto-generates fresh 6-digit codes.

## Best Practices

1. **Always use `sensitive_data`** for passwords — never put them in the task string
2. **Set `use_vision=False`** when dealing with login forms to prevent screenshot leaks
3. **Use `allowed_domains`** to restrict where the browser can navigate
4. **Use `storage_state`** to save/load cookies instead of re-entering passwords
