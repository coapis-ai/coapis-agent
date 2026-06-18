import sys
import os
sys.path.insert(0, os.getcwd())
os.environ["COAPIS_WORKING_DIR"] = "/apps/ai/coapis"

from coapis.providers.provider_manager import ProviderManager
from coapis.config.config import ModelSlotConfig
import json
import asyncio

# Get provider manager instance
pm = ProviderManager.get_instance()

# Step 1: Configure coapis-local provider with base_url (no API key needed for vLLM)
print("Step 1: Configuring coapis-local provider...")
ok = pm.update_provider("coapis-local", {
    "base_url": "http://172.16.6.241:8082/v1",
    "api_key": ""  # vLLM 无需 API key
})
print(f"  update_provider result: {ok}")

# Step 2: Fetch models from the provider
print("Step 2: Fetching models...")
models = asyncio.run(pm.fetch_provider_models("coapis-local", save=True))
print(f"  Found {len(models)} models: {[m.id for m in models]}")

# Step 3: Set as active model
print("Step 3: Setting as active model...")
if models:
    active = ModelSlotConfig(
        provider_id="coapis-local",
        model=models[0].id
    )
    pm.save_active_model(active)
    pm.active_model = active
    print(f"  Active model set: {active.provider_id}/{active.model}")
else:
    print("  No models found, cannot set active model")

# Step 4: Verify
print("Step 4: Verifying...")
info = asyncio.run(pm.get_provider_info("coapis-local"))
print(f"  base_url: {info.base_url}")
print(f"  api_key: '{info.api_key}'")
print(f"  models: {[m.id for m in info.extra_models]}")

print("\n✅ LLM provider configured successfully!")
