import base64
import json
import logging
from pathlib import Path

import httpx

from core.config import settings

logger = logging.getLogger("lens.ollama")

_TIMEOUT       = httpx.Timeout(90.0,  connect=10.0)   # normal pipeline calls
_TIMEOUT_LONG  = httpx.Timeout(900.0, connect=10.0)   # 32b text/vision (can take 6–12 min for long captions)

# 32b vision context — must hold prompt + image vision tokens + num_predict output.
# The rich pass3 prompt (~750 tokens) + a 1024px image (up to ~1280 vision tokens)
# + num_predict=768 = up to ~2800 tokens. 2048 caused 500 errors mid-generation
# on busy compositions (see Ollama log 2026-05-05). 4096 gives comfortable headroom
# at +512 MiB kv cache cost — still fits well in M1 Max 32 GB unified memory.
_VISION_CTX: dict[str, int] = {
    "qwen2.5vl:32b": 4096,
}

# Mode flag file — contains "off", "text", or "auto"
_MODE_FILE = Path("/tmp/lens_mode")

# All known 32b models for unload
_ALL_32B = {"qwen2.5:32b", "qwen2.5vl:32b"}


def get_mode() -> str:
    """Read current mode from flag file. Defaults to 'off'."""
    try:
        return _MODE_FILE.read_text().strip()
    except FileNotFoundError:
        return "off"


def set_mode(mode: str) -> None:
    """Write mode to flag file."""
    _MODE_FILE.write_text(mode)


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.vision_model = settings.vision_model
        self.text_model = settings.text_model

    async def vision(self, image_path: Path, prompt: str, num_predict: int = 512) -> str:
        """Send an image + prompt to the vision model. Returns raw response text."""
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        options = {"num_predict": num_predict}
        if self.vision_model in _VISION_CTX:
            options["num_ctx"] = _VISION_CTX[self.vision_model]

        payload = {
            "model": self.vision_model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": options,
        }
        # Full JSON tagging prompts (num_predict > 256) can take 2-4 min on 32b
        timeout = _TIMEOUT_LONG if num_predict > 256 else _TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json()["response"]

    async def vision_json(self, image_path: Path, prompt: str, num_predict: int = 512) -> dict:
        """Vision call that expects and parses a JSON response."""
        raw = await self.vision(image_path, prompt, num_predict=num_predict)
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        return json.loads(raw)

    async def text(
        self,
        prompt: str,
        system: str | None = None,
        num_predict: int | None = None,
        format: str | None = None,
        keep_alive: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        repeat_penalty: float | None = None,
    ) -> str:
        """Send a text prompt to the text model. Returns raw response text.

        Args:
            num_predict: cap on output tokens. None = model default (can be huge).
            format: pass "json" to use Ollama's server-side constrained JSON decoding.
            keep_alive: how long to keep the model resident after this call
                (e.g. "30m"). None = Ollama default (5m).
            temperature: sampling temperature. None = Ollama default (~0.7).
                Higher (e.g. 1.0–1.2) = more variety, useful for creative writing
                like Instagram captions where the same prompt should produce
                different outputs across calls.
            top_p: nucleus sampling. None = default.
            repeat_penalty: penalize repeated tokens. None = default. Useful for
                breaking the model out of cadence ruts ("...stillness ... pause ...
                connect with ...").
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options: dict = {}
        if num_predict is not None:
            options["num_predict"] = num_predict
        if temperature is not None:
            options["temperature"] = temperature
        if top_p is not None:
            options["top_p"] = top_p
        if repeat_penalty is not None:
            options["repeat_penalty"] = repeat_penalty

        payload: dict = {
            "model": self.text_model,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options
        if format:
            payload["format"] = format
        if keep_alive:
            payload["keep_alive"] = keep_alive

        # 32b text model can take a few minutes for complex prompts
        timeout = _TIMEOUT_LONG if "32b" in self.text_model else _TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    async def text_json(
        self,
        prompt: str,
        system: str | None = None,
        num_predict: int | None = None,
        keep_alive: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        repeat_penalty: float | None = None,
    ) -> dict:
        """Text call that expects and parses a JSON response.

        Uses Ollama's `format: "json"` for server-side constrained decoding —
        the model cannot emit preamble, markdown fences, or text outside JSON.
        """
        raw = await self.text(
            prompt,
            system=system,
            num_predict=num_predict,
            format="json",
            keep_alive=keep_alive,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        return json.loads(raw)

    async def text_with_image(self, image_path: Path, prompt: str, system: str | None = None, num_predict: int = 512) -> str:
        """Send an image + text prompt to the current text model via /api/chat.
        Uses the chat endpoint so Ollama applies the model's chat template correctly."""
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        options = {"num_predict": num_predict}
        if self.text_model in _VISION_CTX:
            options["num_ctx"] = _VISION_CTX[self.text_model]

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt, "images": [image_b64]})

        payload = {
            "model": self.text_model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        timeout = _TIMEOUT_LONG if num_predict > 256 else _TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    async def unload_all(self) -> None:
        """Unload all known models from Ollama to free RAM."""
        models = _ALL_32B | {self.vision_model, self.text_model}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for model in models:
                try:
                    await client.post(
                        f"{self.base_url}/api/generate",
                        json={"model": model, "keep_alive": 0, "prompt": ""},
                    )
                except Exception:
                    pass

    async def preload(self, model: str) -> None:
        """Load a model into memory by sending a trivial request."""
        logger.info(f"Preloading model: {model}")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                await client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": model, "prompt": "hello", "keep_alive": "30m",
                          "options": {"num_predict": 1}},
                )
            logger.info(f"Model {model} preloaded successfully")
        except Exception as e:
            logger.warning(f"Preload failed for {model}: {e}")

    async def switch_mode(self, mode: str) -> dict:
        """Switch operating mode: off, text, auto, or priority.
        - off:      unload everything, pipeline paused
        - text:     unload vision, load qwen2.5:32b for captions
        - auto:     unload text, load qwen2.5vl:32b for pipeline pass3
        - priority: like auto — loads vision model for rush-processing a folder
        """
        old_mode = get_mode()
        if mode == old_mode:
            return {"mode": mode, "changed": False}

        # Always unload everything first to free RAM
        await self.unload_all()

        if mode == "text":
            await self.preload(settings.text_model)  # qwen2.5:32b
        elif mode in ("auto", "priority"):
            await self.preload(settings.vision_model)
            await self.preload("qwen2.5vl:32b")

        set_mode(mode)
        logger.info(f"Mode switched: {old_mode} -> {mode}")
        return {"mode": mode, "previous": old_mode, "changed": True}

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False


ollama = OllamaClient()
