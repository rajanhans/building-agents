"""Check that your computer is ready for the course. Run it BEFORE class:

    python check_setup.py            # from the course folder, with the .venv activated
    %run ../check_setup.py           # or from a notebook (first cell)

Every line is ✅ or ❌ with the exact fix. If anything stays ❌, send the whole output
to your instructor before the session.
"""

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGES = {"openai": "openai", "pydantic": "pydantic", "dotenv": "python-dotenv", "ipykernel": "ipykernel"}
problems: list[str] = []


def ok(msg: str) -> None:
    print(f"✅ {msg}")


def bad(msg: str, fix: str) -> None:
    print(f"❌ {msg}\n   → {fix}")
    problems.append(msg)


def check_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}")
    else:
        bad(f"Python {v.major}.{v.minor} is too old", "Install Python 3.10 or newer from python.org, then recreate .venv.")


def check_venv() -> None:
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    expected = (ROOT / ".venv").resolve()
    here = Path(sys.prefix).resolve()
    if in_venv and here == expected:
        ok(f"Running in the course environment ({here})")
    elif in_venv:
        bad(f"Running in a different environment: {here}",
            "In VS Code: Select Kernel (top right) → Python Environments → .venv. In a terminal: source .venv/bin/activate")
    else:
        bad(f"Not running in a virtual environment ({sys.executable})",
            "Create it once: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt. "
            "In VS Code, select the .venv kernel.")


def check_packages() -> None:
    missing = [pip for mod, pip in PACKAGES.items() if importlib.util.find_spec(mod) is None]
    if missing:
        bad(f"Missing packages: {', '.join(missing)}",
            "With .venv active: pip install -r requirements.txt   (in a notebook: %pip install -r ../requirements.txt)")
    else:
        ok("Packages installed: " + ", ".join(PACKAGES.values()))


def check_key() -> str | None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        bad("No .env file in the course folder", "cp .env.example .env   then open .env and paste your OpenAI key.")
        return None
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        return None
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key or "your-key-here" in key:
        bad("OPENAI_API_KEY is not set in .env", "Open .env, replace sk-proj-your-key-here with your key, save.")
        return None
    if not key.startswith("sk-"):
        bad("OPENAI_API_KEY doesn't look like an OpenAI key (should start with sk-)",
            "Copy the key again from platform.openai.com → API keys.")
        return None
    ok(f"OPENAI_API_KEY found in .env (sk-…{key[-4:]})")
    return key


def check_api(model: str = "gpt-6-luna") -> None:
    try:
        from openai import OpenAI
        r = OpenAI().responses.create(model=model, input="Reply with the single word: ready",
                                      max_output_tokens=200, reasoning={"effort": "low"})
        ok(f"OpenAI API call works ({model} said: {(r.output_text or '').strip()[:30]!r})")
    except Exception as exc:  # show the provider's own message: it usually says what's wrong
        name = type(exc).__name__
        fix = {"AuthenticationError": "The key is wrong or revoked: create a new one and update .env.",
               "PermissionDeniedError": "Your key/project has no access to this model: check model access in the OpenAI dashboard.",
               "RateLimitError": "No credit or rate limit reached: add billing credit at platform.openai.com → Billing.",
               "NotFoundError": f"Model {model!r} not found for your account: tell your instructor.",
               "APIConnectionError": "No connection to api.openai.com: check internet / VPN / firewall."}.get(
            name, "Send this message to your instructor.")
        bad(f"OpenAI API call failed: {name}: {str(exc)[:200]}", fix)


def main(call_api: bool = True) -> bool:
    print(f"Checking setup for the course in {ROOT}\n")
    check_python()
    check_venv()
    check_packages()
    key = check_key()
    if call_api and key and importlib.util.find_spec("openai"):
        check_api()
    print()
    if problems:
        print(f"⚠️  {len(problems)} problem(s). Fix them with the → hints, run this again, and if it still fails, "
              "send this whole output to your instructor before class.")
    else:
        print("🎉 You're ready for class!")
    return not problems


if __name__ == "__main__":
    sys.exit(0 if main(call_api="--no-api" not in sys.argv) else 1)
