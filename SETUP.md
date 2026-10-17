# Before the first class: set up your computer (about 20 minutes)

Do this **at home, before the session**. At the end, a check script tells you whether you're ready.
If it isn't all green, send its output to your instructor **before** class, so we can start on time.

## 1. Install the tools

- **Python 3.10 or newer**: [python.org/downloads](https://www.python.org/downloads/). On Windows, tick *"Add python.exe to PATH"*.
- **VS Code**: [code.visualstudio.com](https://code.visualstudio.com/).
- **Git** (optional): [git-scm.com](https://git-scm.com/downloads). Without git you can download a ZIP instead (step 2).

## 2. Get the course code

```bash
git clone https://github.com/adrianchira/building-agents.git
```

No git? On [the course page](https://github.com/adrianchira/building-agents) click **Code → Download ZIP** and unzip it.

In VS Code: **File → Open Folder…** and open the `building-agents` folder (the whole folder, not a single file).
When VS Code asks *"Do you trust the authors?"* click **Yes, I trust the authors**. If you click No, the Python
extension is switched off and nothing works. Install the recommended extensions (Python, Jupyter) when asked.

## 3. Create the Python environment

In VS Code: **Terminal → New Terminal**, then:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Add your OpenAI key

```bash
cp .env.example .env               # Windows: copy .env.example .env
```

Open `.env` in VS Code, replace `sk-proj-your-key-here` with your key from
[platform.openai.com → API keys](https://platform.openai.com/api-keys), and save.
Set a monthly spending limit there too (the whole course costs a few dollars at most).

Never paste the key into a notebook or a `.py` file. `.env` is never uploaded to GitHub.

## 5. Run the check

```bash
python check_setup.py
```

You should see all ✅ and **🎉 You're ready for class!** Every ❌ line comes with the fix (→). The most common ones:

| You see | Fix |
|---|---|
| `Not running in a virtual environment` | `source .venv/bin/activate` (step 3) |
| `Missing packages` | `pip install -r requirements.txt` with the environment active |
| `No .env file` / `OPENAI_API_KEY is not set` | Step 4 |
| `AuthenticationError` | The key is wrong: copy it again or create a new one |
| `RateLimitError` | Add billing credit to your OpenAI account |

## 6. Open a notebook once

Open `week-01-agentic-loop/01_agentic_loop.ipynb`. Click **Select Kernel** (top right) → **Python Environments** →
`.venv`. Run the first two cells. If they work, you're done.

| VS Code says | Fix |
|---|---|
| "Python Extension not installed" / kernel list is empty | You're in *Restricted Mode*: click it in the status bar → **Trust**, then ⇧⌘P / Ctrl+Shift+P → *Developer: Reload Window* |
| `No module named ...` | Wrong kernel: Select Kernel → `.venv` |
| `No OPENAI_API_KEY found` | Step 4, then restart the kernel |

Still stuck? Send the output of `python check_setup.py` to your instructor.
