# GabaMic — Voice-to-Text Dictation

Hold **Alt+S**, speak, release — your words are typed into whatever app is in focus.
Runs entirely on your machine. No cloud, no subscription, no data sent anywhere.

---

## Windows

### Option A — Download the app (no Python, no setup)

This is the easiest path. A pre-built `.exe` is built automatically by GitHub Actions
and attached to every release.

1. Go to **[github.com/AGabarro/GabaMic/releases](https://github.com/AGabarro/GabaMic/releases)**
2. Under the latest release, download **`GabaMic-Windows.zip`**
3. Extract the zip to any folder (e.g. `C:\GabaMic`)
4. Double-click **`GabaMic.exe`** inside the extracted folder

A small pill appears at the bottom-centre of your screen.

> **First launch only:** the pill shows "Downloading model…" for a few minutes while
> the speech model (~150 MB) downloads. Your internet connection is required for this
> one-time step. After that, GabaMic works fully offline forever.

Once the animated logo appears, GabaMic is ready. See **[Using GabaMic](#using-gabamic)** below.

---

### Option B — Run from source (requires Python, one-time setup)

Use this if no pre-built release is available yet, or if you want to run the latest code.

**Step 1 — Install Python (skip if already installed)**

Download Python 3.10 or newer from **[python.org/downloads](https://www.python.org/downloads/)**.

On the installer's first screen, tick **"Add Python to PATH"** before clicking Install.

**Step 2 — Download GabaMic**

Download **[GabaMic-main.zip](https://github.com/AGabarro/GabaMic/archive/refs/heads/main.zip)**
and extract it anywhere (e.g. `C:\GabaMic`).

**Step 3 — Run the setup script (one time only)**

Inside the extracted folder, double-click **`setup_windows.bat`**.

It will:
- Check your Python version
- Create an isolated environment
- Download and install all dependencies
- Offer to launch GabaMic immediately when done

**Step 4 — Launch GabaMic**

From now on, just double-click **`GabaMic.bat`** to start.

---

## macOS

### Step 1 — Download GabaMic

Either download the zip:

**[github.com/AGabarro/GabaMic/archive/refs/heads/main.zip](https://github.com/AGabarro/GabaMic/archive/refs/heads/main.zip)**

…or clone the repo if you have git:

```bash
git clone https://github.com/AGabarro/GabaMic.git
```

### Step 2 — Install dependencies

Open **Terminal**, navigate to the GabaMic folder, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 3 — Run

```bash
source .venv/bin/activate
python app.py
```

A **🎙** icon appears in the menu bar. A small pill also appears at the bottom of your
screen. GabaMic is ready.

> **Accessibility permission (one time):** the first time you press Alt+S, macOS may
> show a permission prompt. Click **Open System Settings**, then turn on the toggle
> for Terminal (or the app) under **Privacy & Security → Accessibility**. Restart the
> script once. This is required for global hotkey detection and is a one-time step.

---

## Using GabaMic

Once running, the pill sits at the bottom-centre of your screen above all other windows.

| Pill state | Meaning |
|---|---|
| Animated logo (cyan glow) | Ready — waiting for you to press Alt+S |
| Orange dot · "Recording…" | Listening to your microphone |
| Orange dot · "Transcribing…" | Converting speech to text |
| Cyan dot · transcribed text | Done — text has been pasted into your app |
| Cyan dot · "Downloading model…" | First-run model download in progress |
| Cyan dot · "Warming up…" | Model is loading (normal on startup) |

**How to dictate:**

1. Click into the app / text field where you want the text to appear
2. Hold **Alt+S** and speak
3. Release **Alt+S**
4. The transcribed text is pasted automatically

**To quit:** right-click the pill.

**macOS only:** click the 🎙 menu bar icon to switch language between
Auto-detect, English, and Spanish.

---

## Changing the hotkey

Open **`config.json`** (next to the `.exe` or in the GabaMic folder) and edit:

```json
"hotkey_modifier": "alt",
"hotkey_key": "s"
```

| `hotkey_modifier` | Key |
|---|---|
| `"alt"` | Alt (Windows) / Option (macOS) |
| `"ctrl"` | Control |
| `"shift"` | Shift |
| `"cmd"` | Command — macOS only |

Change `hotkey_key` to any single letter, e.g. `"r"` for **Alt+R**.

---

## Other settings (`config.json`)

| Setting | Default | What it does |
|---|---|---|
| `model_size` | `"base"` | `"tiny"` is fastest; `"small"` or `"medium"` are more accurate but slower to load |
| `language` | `null` | `null` = auto-detect language. Set to `"en"`, `"es"`, `"fr"`, etc. to force a language |
| `silence_rms_threshold` | `0.01` | Lower to `0.005` if quiet speech isn't being picked up |
| `min_recording_seconds` | `0.5` | Minimum recording length; raise if very short phrases are missed |

---

## Troubleshooting

**Pill shows "Downloading model…" for a long time**
→ The ~150 MB speech model is downloading. Leave it running — it only happens once.
Check your internet connection if it never finishes.

**Alt+S does nothing (Windows)**
→ Wait until the animated logo appears — the hotkey is not active during "Warming up…".
→ Some security software blocks global keyboard listeners. Right-click `GabaMic.bat`
and choose **Run as administrator**.
→ If Alt+S is claimed by another app, change the hotkey in `config.json`.

**Alt+S does nothing (macOS)**
→ Accessibility permission is missing. Go to **System Settings → Privacy & Security →
Accessibility**, add Terminal (or the app), toggle it on, and restart the script.

**Text is not pasted into my app**
→ Click into the target text field *before* releasing Alt+S. GabaMic pastes via
`Ctrl+V` on Windows and `Cmd+V` on macOS — the target window must be focused.

**"No speech detected" / empty result**
→ Lower `silence_rms_threshold` to `0.005` in `config.json`.
→ Hold Alt+S for at least half a second before speaking.

**`GabaMic.exe` crashes on launch (Windows)**
→ Make sure Microsoft Edge WebView2 is installed. It ships with every Windows 11 machine
and with Windows 10 (21H2 and later). If missing, download the Evergreen Bootstrapper
from **[developer.microsoft.com/en-us/microsoft-edge/webview2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)**.

**`app.py` fails on Windows**
→ `app.py` uses macOS-only system libraries. Use `GabaMic.exe` or `GabaMic.bat` instead.

---

## For developers — building the Windows .exe

The `.exe` is built automatically by GitHub Actions on every tagged release.
To trigger a build manually:

1. Push your changes to GitHub
2. Go to **Actions → Build Windows Executable → Run workflow**

To build locally on a Windows machine:

```bat
setup_windows.bat        :: one-time setup
build_windows.bat        :: produces dist\GabaMic\GabaMic.exe
```

Zip `dist\GabaMic\` and it is ready to distribute — no installer, no Python required
for the end user.
