import json

from google import genai
from google.genai import types

from app.config import get_settings

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiAPIError(Exception):
    pass


def generate_text(prompt: str, model: str = DEFAULT_MODEL) -> str:
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = client.models.generate_content(model=model, contents=prompt)
    except Exception as exc:
        raise GeminiAPIError(str(exc)) from exc
    return response.text.strip()


def generate_text_with_images(prompt: str, image_paths: list[str], model: str = DEFAULT_MODEL) -> str:
    """Call Gemini with a text prompt plus one or more local images (e.g. video frames)."""
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)

    contents: list = [prompt]
    for path in image_paths:
        with open(path, "rb") as f:
            contents.append(types.Part.from_bytes(data=f.read(), mime_type="image/jpeg"))

    try:
        response = client.models.generate_content(model=model, contents=contents)
    except Exception as exc:
        raise GeminiAPIError(str(exc)) from exc
    return response.text.strip()


def generate_json(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Call Gemini with JSON-only output mode and parse the result."""
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except Exception as exc:
        raise GeminiAPIError(str(exc)) from exc

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GeminiAPIError(f"Could not parse Gemini JSON response: {response.text!r}") from exc
