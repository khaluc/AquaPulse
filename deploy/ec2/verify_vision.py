"""Run inside the web container to verify the configured image provider."""
from app.vision import load_default_vision
from PIL import Image

client = load_default_vision()
if client is None:
    raise SystemExit("Vision is disabled or its API key is missing.")
result = client.analyze(Image.new("RGB", (128, 128), "white"))
print(f"provider={result.provider} model={result.model} elapsed_ms={result.elapsed_ms:.0f}")
print(f"Parsed signals: {len(result.signals)}")
