# GabaMic — Voice-to-Text Dictation

Hold **Alt+S**, speak, release — your words are typed into whatever app is in focus.
Everything runs locally: no cloud, no subscription, no data sent anywhere.

---

## Platform Overview

| Entry point | macOS | Windows | Linux |
|---|---|---|---|
| `app.py` — menu bar + floating pill | ✅ | ✗ | ✗ |
| `app_win.py` — floating pill | ✗ | ✅ | ✗ |
| `main.py` — terminal only | ✅ | ✅ | ✅ (X11) |
| `web.py` — browser widget | ✅ | ✅ | ✅ |

---

## Requirements

| Requirement | macOS | Windows |
|---|---|---|
| Python | 3.10 or newer | 3.10 or newer |
| Microphone | ✅ | ✅ |
| Accessibility permission | Required for `app.py` / `main.py` | Not required |
| WebView2 runtime | — | Required for `app_win.py` — ships with Windows 10 (KB4577586+) and all Windows 11 |

> **First run:** the Whisper speech model (~150 MB) downloads automatically and is cached. All subsequent runs are fully offline.

---

## Installation

### macOS

```bash
git clone https://github.com/YOUR_USERNAME/GabaMic.git
cd GabaMic

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### Windows

Open **PowerShell** (or Command Prompt):

```powershell
git clone https://github.com/YOUR_USERNAME/GabaMic.git
cd GabaMic

python -m venv .venv
.venv\Scripts\Activate.ps1        # PowerShell
# — or —
.venv\Scripts\activate.bat         # Command Prompt

pip install -r requirements.txt
pip install pywebview>=4.0.2       # only needed for app_win.py
```

> **PowerShell execution policy:** if `Activate.ps1` is blocked, run:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

---

## How to Run

### macOS — Floating Pill + Menu Bar (recommended)

```bash
source .venv/bin/activate
python app.py
```

A **🎙** icon appears in the menu bar and a small pill overlay appears at the bottom of your screen. Hold **Alt+S** anywhere to record, release to transcribe. The text is typed into whatever app is focused.

- Pill turns orange while recording, shows the transcribed text for 2.5 s, then returns to idle.
- Click the menu bar icon to switch language: Auto-detect → English → Spanish.

> Requires **Accessibility permission** — see the macOS section below.

---

### Windows — Floating Pill (recommended)

```powershell
.venv\Scripts\Activate.ps1
python app_win.py
```

A **240 × 44 px pill** appears at the bottom-centre of your screen. It stays above all other windows.

- Hold **Alt+S** to record → orange dot + "Recording…"
- Release → "Transcribing…" → text is pasted into the focused window
- **Right-click the pill to quit**

No Accessibility permission or admin rights required. WebView2 must be installed (it is on every up-to-date Windows 10 / 11 machine).

**If the pill window appears but the hotkey does nothing:**
Some security software blocks pynput's global keyboard listener. Run PowerShell as administrator and retry.

---

### All Platforms — Browser Widget

```bash
# macOS / Linux
source .venv/bin/activate
python web.py

# Windows
.venv\Scripts\Activate.ps1
python web.py
```

Opens `http://localhost:8765` automatically. Click-and-hold the logo to record, release to transcribe. The result appears in an editable text box and is auto-copied to your clipboard.

Works on every platform with no system permissions. The browser asks for microphone access on first use.

---

### macOS / Linux — Terminal (headless)

```bash
source .venv/bin/activate
python main.py
```

Hold **Alt+S** to record, release to transcribe. Output is printed to the terminal and pasted into the focused app. Quit with **Ctrl+C**.

---

## macOS: Accessibility Permission

`app.py` and `main.py` need permission to listen for the hotkey system-wide.

1. Run the app and press **Alt+S** once — macOS will show a permission prompt.
2. Open **System Settings → Privacy & Security → Accessibility**.
3. Add **Terminal** (for `main.py`) or the app bundle (for `app.py`) and turn the toggle on.
4. Restart the script.

This is a one-time step. `web.py` does not need this permission.

---

## Windows: WebView2 Check

`app_win.py` requires the **Microsoft Edge WebView2 Runtime**. To check if it is installed:

1. Open **Settings → Apps → Installed apps**
2. Search for **"WebView2"**

If it is not listed, download the Evergreen Bootstrapper from:
**https://developer.microsoft.com/en-us/microsoft-edge/webview2/**

Most Windows 10 (21H2+) and all Windows 11 machines already have it.

---

## Changing the Hotkey

Open `config.json` and edit:

```json
"hotkey_modifier": "alt",
"hotkey_key": "s"
```

| `hotkey_modifier` | Key |
|---|---|
| `"alt"` | Alt / Option |
| `"ctrl"` | Control |
| `"shift"` | Shift |
| `"cmd"` | Command (macOS only) |

Set `hotkey_key` to any single letter, e.g. `"r"` for **Alt+R**.

---

## Other Settings (`config.json`)

| Setting | Default | What it does |
|---|---|---|
| `model_size` | `"base"` | Whisper model size. `"tiny"` is fastest; `"small"` / `"medium"` are more accurate but slower. |
| `language` | `null` | `null` = auto-detect. Force a language with `"en"`, `"es"`, `"fr"`, etc. |
| `silence_rms_threshold` | `0.01` | Lower this (e.g. `0.005`) if quiet speech is not being picked up. |
| `min_recording_seconds` | `0.5` | Minimum recording length before transcription is attempted. |

---

## Troubleshooting

**Nothing happens when I press Alt+S (macOS)**
→ Accessibility permission is missing — follow the steps above.

**Nothing happens when I press Alt+S (Windows)**
→ Some antivirus or security software blocks pynput. Try running PowerShell as Administrator.
→ If Alt+S conflicts with another app, change the hotkey in `config.json`.

**The pill appears but text is not pasted**
→ On Windows, make sure the target app is focused *before* releasing Alt+S. GabaMic uses `Ctrl+V` to paste.

**"No speech detected"**
→ Lower `silence_rms_threshold` to `0.005` in `config.json`. Hold the key for at least half a second.

**Slow on first run**
→ The Whisper model is downloading (~150 MB). Subsequent runs are instant.

**`app_win.py` crashes with "WebView2 not found"**
→ Install the WebView2 Runtime from the link in the Windows section above.

**`app.py` fails on Windows or Linux**
→ `app.py` uses macOS-only system libraries. Use `app_win.py` (Windows) or `web.py` (all platforms).

**PowerShell says "cannot be loaded because running scripts is disabled"**
→ Run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
