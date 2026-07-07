# Getting Started

## Prerequisites

- Python 3.10+
- Google Chrome (for Mode B)
- An OpenAI-compatible API key (GPT-4o-mini recommended)

## Install the Skill

```bash
clawhub install browser-use
```

Or manually copy to `~/.openclaw/skills/browser-use/`

## Setup Python Environment (One-Time)

```bash
python3 -m venv ~/browser-use-env
source ~/browser-use-env/bin/activate
pip install browser-use playwright langchain-openai
playwright install chromium
```

## Your First Automation

```python
import asyncio
from browser_use import Agent, ChatOpenAI, Browser

async def main():
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key="YOUR_KEY",
        base_url="https://api.openai.com/v1",
    )
    browser = Browser(headless=False)

    agent = Agent(
        task="Go to https://example.com and tell me the page title",
        llm=llm, browser=browser, max_steps=5,
    )
    result = await agent.run()
    print(result)

asyncio.run(main())
```

Run it:
```bash
source ~/browser-use-env/bin/activate
python3 my_first_task.py
```

🎉 You should see Browser-Use open a browser, navigate to the page, and return the title!
