# Cognee API Integration Skill

This skill teaches the agent how to correctly interact with the Cognee Cloud API using environment variables.

## Environment Variables
The agent must NEVER hardcode API keys or URLs. Instead, it must rely on the following environment variables:
- `COGNEE_API_BASE_URL`: The tenant-specific base URL (e.g., `https://tenant-xxxx-xxxx.aws.cognee.ai`)
- `COGNEE_API_KEY`: The tenant-specific API Key

## How to authenticate
Pass the API key in the `X-Api-Key` header for all requests to the Cognee API.

```python
import os
import requests

COGNEE_API_BASE_URL = os.environ.get("COGNEE_API_BASE_URL", "").rstrip("/")
COGNEE_API_KEY = os.environ.get("COGNEE_API_KEY", "")

headers = {
    "X-Api-Key": COGNEE_API_KEY,
    "Content-Type": "application/json"
}

# Example Request
response = requests.post(
    f"{COGNEE_API_BASE_URL}/api/v1/remember",
    headers=headers,
    ...
)
```

## Important Notes
- Cognee recently migrated to tenant-specific URLs. Do not use the deprecated `https://api.cognee.ai` endpoint.
- Always use `os.environ.get()` to load the URL and key.
