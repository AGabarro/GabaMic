"""GabaMic — browser-based push-to-talk for testing without system permissions.

Audio is captured entirely in the browser (getUserMedia + Web Audio API) and
POSTed as raw float32 PCM to /transcribe. Python never calls sounddevice, so
the terminal process does NOT need Microphone permission in System Settings.

Usage:
    python web.py
    → opens http://localhost:8765 automatically
    → hold Spacebar or hold the button to record, release to transcribe
    → text appears in the editable area; edit it, then copy with the button
    → auto-copied to clipboard on each transcription
"""

import http.server
import json
import pathlib
import webbrowser

import numpy as np

from gabamic.transcriber import Transcriber

CONFIG_PATH = pathlib.Path(__file__).parent / "config.json"
PORT = 8765

_transcriber: Transcriber | None = None
_silence_rms_threshold: float = 0.01
_min_recording_seconds: float = 0.5
_LOGO_PATH = pathlib.Path(__file__).parent / "GabaMic.png"

# ---------------------------------------------------------------------------
# Inline HTML / CSS / JS
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="GabaMic">
  <title>GabaMic</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='15' y1='185' x2='185' y2='15' gradientUnits='userSpaceOnUse'%3E%3Cstop offset='0%25' stop-color='%2300FFEF'/%3E%3Cstop offset='100%25' stop-color='%23FF6200'/%3E%3C/linearGradient%3E%3C/defs%3E%3Ccircle cx='100' cy='100' r='69' fill='none' stroke='url(%23g)' stroke-width='32' stroke-dasharray='361.3 72.3'/%3E%3Crect x='100' y='84' width='85' height='32' fill='url(%23g)'/%3E%3C/svg%3E">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    /* ── Palette ──────────────────────────────────────────────────────────── */
    :root {
      --teal:         #00FFEF;
      --teal-40:      rgba(0,255,239,0.40);
      --teal-25:      rgba(0,255,239,0.25);
      --teal-12:      rgba(0,255,239,0.12);
      --teal-06:      rgba(0,255,239,0.06);
      --orange:       #FF6200;
      --orange-70:    rgba(255,98,0,0.70);
      --orange-30:    rgba(255,98,0,0.30);
      --orange-12:    rgba(255,98,0,0.12);
      --bg:           #080B14;
      --card:         #0C0F1C;
      --visual-bg:    #060810;
      --text:         #E6FFFD;
      --text-dim:     rgba(0,255,239,0.55);
      --text-faint:   rgba(0,255,239,0.30);
      --divider:      rgba(0,255,239,0.10);
    }

    /* ── Page ─────────────────────────────────────────────────────────────── */
    body {
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                   "Helvetica Neue", Arial, sans-serif;
      background: radial-gradient(ellipse at 50% 20%, #0E1830 0%, var(--bg) 65%);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      -webkit-font-smoothing: antialiased;
    }

    /* ── Widget shell ─────────────────────────────────────────────────────── */
    .widget {
      width: 360px;
      background: var(--card);
      border: 1px solid var(--teal-25);
      border-radius: 22px;
      box-shadow:
        0 0 0 1px rgba(0,255,239,0.04),
        0 28px 70px rgba(0,0,0,0.65),
        0 0 60px rgba(0,255,239,0.05);
      overflow: hidden;
      user-select: none;
    }

    /* ── Header bar ───────────────────────────────────────────────────────── */
    .header {
      display: flex;
      align-items: center;
      gap: 9px;
      padding: 14px 16px 14px 18px;
      border-bottom: 1px solid var(--divider);
    }

    .header-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
      background: var(--orange);
      box-shadow: 0 0 8px var(--orange), 0 0 16px var(--orange-30);
      transition: background 0.3s, box-shadow 0.3s;
    }
    .header-dot.teal {
      background: var(--teal);
      box-shadow: 0 0 8px var(--teal), 0 0 16px var(--teal-25);
    }
    .header-dot.pulse {
      animation: dot-pulse 0.9s ease-in-out infinite;
    }
    @keyframes dot-pulse {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.35; }
    }

    .header-title {
      flex: 1;
      text-align: center;
      font-size: 10.5px;
      font-weight: 700;
      letter-spacing: 1.4px;
      text-transform: uppercase;
      color: var(--text-dim);
    }

    .header-close {
      background: none;
      border: none;
      color: var(--text-faint);
      font-size: 18px;
      line-height: 1;
      cursor: pointer;
      padding: 0;
      transition: color 0.2s;
      flex-shrink: 0;
    }
    .header-close:hover { color: var(--text-dim); }

    /* ── Visual area ──────────────────────────────────────────────────────── */
    .visual-wrap {
      padding: 16px 16px 0;
    }

    /*
     * Gradient-border wrapper — CSS can't gradient a border on a border-radius
     * box, so we use a padding + background trick: the wrapper's background
     * shows through the 1.5 px padding gap as the "border".
     */
    .visual-frame {
      border-radius: 17.5px;          /* inner-radius (16) + border-width (1.5) */
      padding: 1.5px;
      background: rgba(0,255,239,0.25);    /* default: teal border */
      box-shadow: 0 0 28px rgba(0,255,239,0.06);
      transition: background 0.35s ease, box-shadow 0.35s ease;
    }
    .visual-frame.recording {
      background: rgba(255,98,0,0.65);
      box-shadow:
        0 0 36px rgba(255,98,0,0.12),
        0 0 72px rgba(255,98,0,0.07);
    }
    .visual-frame.transcribing {
      /* teal on the left, orange on the right — matches the mock */
      background: linear-gradient(90deg, #00FFEF 0%, #FF6200 100%);
      box-shadow:
        -24px 0 40px rgba(0,255,239,0.22),
         24px 0 40px rgba(255,98,0,0.22);
    }

    .visual-area {
      position: relative;
      height: 196px;
      border-radius: 16px;
      background: var(--visual-bg);
      box-shadow: inset 0 0 30px rgba(0,0,0,0.4);
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    /* ── Idle: logo ──────────────────────────────────────────────────────── */
    .logo-stage {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      height: 100%;
      position: relative;
      cursor: pointer;
    }

    /* Radial glow aura that pulses behind the G */
    .logo-aura {
      position: absolute;
      width: 56%;
      height: 78%;
      border-radius: 50%;
      background: radial-gradient(ellipse at center,
        rgba(0,255,239,0.14) 0%,
        rgba(255,98,0,0.09) 42%,
        transparent 68%);
      animation: aura-pulse 3.5s cubic-bezier(0.45,0,0.55,1) infinite;
      pointer-events: none;
      will-change: transform, opacity;
    }
    @keyframes aura-pulse {
      0%, 100% { transform: scale(0.88); opacity: 0.45; }
      50%       { transform: scale(1.15); opacity: 0.95; }
    }

    /* Expanding ring pulses — sonar / heartbeat feel */
    .logo-ring {
      position: absolute;
      width: 44%;
      height: 62%;
      border-radius: 50%;
      border: 1.5px solid rgba(0,255,239,0.30);
      animation: ring-expand 3.5s cubic-bezier(0.2,0,0.4,1) infinite;
      pointer-events: none;
      will-change: transform, opacity;
    }
    @keyframes ring-expand {
      0% {
        transform: scale(0.85);
        opacity: 0;
        border-color: rgba(0,255,239,0.40);
      }
      8% {
        opacity: 0.45;
      }
      100% {
        transform: scale(1.65);
        opacity: 0;
        border-color: rgba(255,98,0,0.15);
      }
    }

    /* The inline SVG G — resolution-independent, no background */
    .idle-logo-svg {
      position: relative;
      z-index: 1;
      height: 80%;
      width: auto;
      animation: logo-breathe 3.5s cubic-bezier(0.45,0,0.55,1) infinite;
      will-change: transform, filter;
    }
    @keyframes logo-breathe {
      0%, 100% {
        filter: drop-shadow(0 0  6px rgba(0,255,239,0.22))
                drop-shadow(0 0 14px rgba(255,98,0,0.10));
        transform: scale(0.98);
      }
      50% {
        filter: drop-shadow(0 0 16px rgba(0,255,239,0.55))
                drop-shadow(0 0 36px rgba(255,98,0,0.30))
                drop-shadow(0 0  5px rgba(255,180,0,0.12));
        transform: scale(1.02);
      }
    }

    /* ── Recording: waveform bars ─────────────────────────────────────────── */
    .waveform {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 3.5px;
      height: 100%;
      width: 100%;
      padding: 0 18px;
    }
    .wv-bar {
      flex: 1;
      max-width: 6px;
      border-radius: 3px;
      background: var(--orange);
      box-shadow: 0 0 6px var(--orange-30);
      animation: bar-bounce var(--dur, 0.5s) ease-in-out infinite;
      animation-delay: var(--dly, 0s);
    }
    @keyframes bar-bounce {
      0%, 100% { height: 6px; }
      50%       { height: var(--mh, 40px); }
    }

    /* ── Transcribing: horizontal speed-line streaks ─────────────────────── */
    .transcribing-stage {
      position: absolute;
      inset: 0;
      overflow: hidden;
      /* ambient glow from the teal side and the orange side */
      background:
        radial-gradient(ellipse at 18% 50%, rgba(0,255,239,0.08) 0%, transparent 52%),
        radial-gradient(ellipse at 82% 50%, rgba(255,98,0,0.08) 0%, transparent 52%);
    }

    /* Each streak is a wrapper that flies left→right as a unit */
    .t-streak-wrap {
      position: absolute;
      display: flex;
      align-items: center;
      animation: t-fly linear infinite;
    }
    .t-streak-line {
      height: 2px;
      border-radius: 1px;
      /* gradient set inline: transparent tail → colour head */
    }
    .t-streak-dot {
      width: 5px;
      height: 5px;
      border-radius: 50%;
      flex-shrink: 0;
      filter: blur(0.6px);
      /* colour and glow set inline */
    }
    @keyframes t-fly {
      0%   { transform: translateX(0);     opacity: 0; }
      6%   { opacity: 1; }
      88%  { opacity: 1; }
      100% { transform: translateX(640px); opacity: 0; }
    }

    /* ── Done: shooting-star particles ───────────────────────────────────── */
    .particles-stage {
      position: absolute;
      inset: 0;
      overflow: hidden;
    }
    .streak {
      position: absolute;
      height: 2px;
      border-radius: 1px;
      transform: rotate(-22deg);
      animation: streak-fly linear infinite;
      opacity: 0;
    }
    @keyframes streak-fly {
      0%   { transform: rotate(-22deg) translateX(-60px); opacity: 0; }
      8%   { opacity: 1; }
      88%  { opacity: 0.9; }
      100% { transform: rotate(-22deg) translateX(420px); opacity: 0; }
    }

    /* ── Status text area ─────────────────────────────────────────────────── */
    .status-section {
      padding: 14px 18px 6px;
      min-height: 56px;
    }

    #status-message {
      font-size: 13px;
      color: var(--text-dim);
      text-align: center;
      transition: opacity 0.3s;
    }

    #status-tagline {
      margin-top: 8px;
      font-size: 19px;
      font-weight: 800;
      color: var(--text);
      letter-spacing: -0.2px;
      line-height: 1.25;
      text-align: center;
      display: none;
    }
    #status-tagline.visible { display: block; }

    /* ── Transcription ────────────────────────────────────────────────────── */
    .transcript-section {
      padding: 4px 16px 14px;
    }

    .section-label {
      font-size: 9.5px;
      font-weight: 700;
      letter-spacing: 1.1px;
      text-transform: uppercase;
      color: var(--text-faint);
      margin-bottom: 7px;
    }

    #transcript {
      display: block;
      width: 100%;
      min-height: 84px;
      max-height: 170px;
      padding: 11px 13px;
      border: 1.5px solid var(--divider);
      border-radius: 12px;
      background: rgba(0,255,239,0.03);
      font-family: inherit;
      font-size: 14px;
      line-height: 1.55;
      color: var(--text);
      resize: vertical;
      outline: none;
      caret-color: var(--teal);
      transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
      user-select: text;
    }
    #transcript:focus {
      border-color: var(--teal-40);
      background: rgba(0,255,239,0.05);
      box-shadow: 0 0 0 3px rgba(0,255,239,0.08);
    }
    #transcript::placeholder { color: var(--text-faint); }

    .actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 9px;
    }

    .char-count {
      font-size: 11px;
      color: var(--text-faint);
      padding-left: 2px;
    }

    #copy-btn {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 7px 16px;
      border-radius: 9px;
      border: none;
      font-family: inherit;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.2px;
      cursor: pointer;
      background: var(--orange);
      color: #fff;
      box-shadow: 0 0 18px var(--orange-30);
      transition: background 0.18s, box-shadow 0.2s, transform 0.12s, opacity 0.2s;
    }
    #copy-btn:disabled {
      opacity: 0.25;
      cursor: default;
      box-shadow: none;
    }
    #copy-btn:not(:disabled):hover {
      background: #FF7A20;
      box-shadow: 0 0 28px var(--orange-30);
    }
    #copy-btn:not(:disabled):active { transform: scale(0.96); }
    #copy-btn.success {
      background: var(--teal);
      color: var(--bg);
      box-shadow: 0 0 20px var(--teal-25);
    }

    /* ── Footer ───────────────────────────────────────────────────────────── */
    .footer {
      padding: 0 16px 14px;
      font-size: 10.5px;
      color: var(--text-faint);
      text-align: center;
      letter-spacing: 0.2px;
    }
  </style>
</head>
<body>
<div class="widget">

  <!-- Header -->
  <div class="header">
    <div class="header-dot" id="header-dot"></div>
    <span class="header-title">Gabamic — Voice Mode</span>
    <button class="header-close" title="Close" onclick="window.close()">&#x2715;</button>
  </div>

  <!-- Visual area -->
  <div class="visual-wrap">
    <div class="visual-frame" id="visual-frame">
      <div class="visual-area" id="visual-area">
        <!-- filled by JS -->
      </div>
    </div>
  </div>

  <!-- Status -->
  <div class="status-section">
    <div id="status-message">Hold the logo to record</div>
    <div id="status-tagline">YOUR VOICE, INSTANTLY TYPED.</div>
  </div>

  <!-- Transcription -->
  <div class="transcript-section">
    <div class="section-label">Transcription</div>
    <textarea id="transcript"
              placeholder="Your speech will appear here — edit before copying…"
              spellcheck="true"></textarea>
    <div class="actions">
      <span class="char-count" id="char-count"></span>
      <button id="copy-btn" disabled>
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
          <rect x="4.5" y="4.5" width="7" height="7" rx="1.5"
                stroke="currentColor" stroke-width="1.4"/>
          <path d="M8.5 4.5V3a1 1 0 0 0-1-1H2a1 1 0 0 0-1 1v5.5
                   a1 1 0 0 0 1 1H4"
                stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
        </svg>
        Copy
      </button>
    </div>
  </div>

  <div class="footer">localhost only &middot; no data leaves this machine</div>

</div><!-- .widget -->

<script>
'use strict';

const TARGET_RATE = 16000;

const visualArea  = document.getElementById('visual-area');
const visualFrame = document.getElementById('visual-frame');
const headerDot   = document.getElementById('header-dot');
const statusMsg   = document.getElementById('status-message');
const statusTag   = document.getElementById('status-tagline');
const transcript  = document.getElementById('transcript');
const copyBtn     = document.getElementById('copy-btn');
const charCount   = document.getElementById('char-count');
const COPY_HTML   = copyBtn.innerHTML;

let uiState     = 'idle';
let recording   = false;
let mediaStream = null;
let audioCtx    = null;
let sourceNode  = null;
let processor   = null;
let silentGain  = null;
let chunks      = [];

// ── Build visual content per state ──────────────────────────────────────────

function buildIdle() {
  const stage = document.createElement('div');
  stage.className = 'logo-stage';
  stage.innerHTML = `
    <div class="logo-aura"></div>
    <div class="logo-ring"></div>
    <div class="logo-ring" style="animation-delay:1.75s"></div>
    <svg class="idle-logo-svg" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="gGrad" x1="15" y1="185" x2="185" y2="15"
                        gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#00FFEF"/>
          <stop offset="100%" stop-color="#FF6200"/>
        </linearGradient>
      </defs>
      <circle cx="100" cy="100" r="69"
              fill="none" stroke="url(#gGrad)" stroke-width="32"
              stroke-dasharray="361.3 72.3"/>
      <rect x="100" y="84" width="85" height="32" fill="url(#gGrad)"/>
    </svg>
  `;
  return stage;
}

function buildWaveform() {
  const wrap = document.createElement('div');
  wrap.className = 'waveform';

  // Sine-envelope: bars in the centre are taller
  const N = 30;
  for (let i = 0; i < N; i++) {
    const bar = document.createElement('div');
    bar.className = 'wv-bar';
    const centre = Math.sin((i / (N - 1)) * Math.PI);    // 0→1→0
    const maxH   = 12 + centre * 90 + (Math.random() * 22 - 11);
    const dur    = (0.32 + Math.random() * 0.52).toFixed(3);
    const dly    = (-(Math.random() * 0.8)).toFixed(3);   // negative = pre-start
    bar.style.cssText = `--mh:${maxH}px; --dur:${dur}s; --dly:${dly}s;`;
    wrap.appendChild(bar);
  }
  return wrap;
}

function buildTranscribing() {
  const stage = document.createElement('div');
  stage.className = 'transcribing-stage';

  // Spread streaks across the visual area height.
  // A sine envelope makes central streaks longer, mimicking the mock.
  const ROWS = 11;
  for (let i = 0; i < ROWS; i++) {
    const wrap = document.createElement('div');
    wrap.className = 't-streak-wrap';

    const topPct = 10 + (i / (ROWS - 1)) * 78 + (Math.random() * 5 - 2.5);
    const centre = Math.sin((i / (ROWS - 1)) * Math.PI);   // 0 → 1 → 0
    const len    = 24 + centre * 115 + (Math.random() * 28 - 14);

    // Alternate orange / teal, biased by position
    const isOrg  = (i % 2 === 0) ? Math.random() > 0.25 : Math.random() > 0.65;
    const color  = isOrg ? '#FF6200' : '#00FFEF';
    const glow   = isOrg ? 'rgba(255,98,0,0.6)' : 'rgba(0,255,239,0.6)';

    const dur  = (0.85 + Math.random() * 1.3).toFixed(2);
    // Negative delay = each streak is pre-started at a random phase → immediate motion
    const dly  = (-(Math.random() * 2.2)).toFixed(2);

    wrap.style.cssText =
      `top:${topPct}%; left:-${Math.round(len + 28)}px;` +
      `animation-duration:${dur}s; animation-delay:${dly}s;`;

    // Tail: transparent on the left, colour on the right
    const line = document.createElement('div');
    line.className = 't-streak-line';
    line.style.cssText =
      `width:${Math.round(len)}px;` +
      `background:linear-gradient(90deg, transparent 0%, ${color} 100%);` +
      `box-shadow:0 0 4px ${glow};`;

    // Bright leading dot at the right tip of the tail
    const dot = document.createElement('div');
    dot.className = 't-streak-dot';
    dot.style.cssText =
      `background:${color};` +
      `box-shadow:0 0 6px ${color}, 0 0 14px ${glow};`;

    wrap.appendChild(line);
    wrap.appendChild(dot);
    stage.appendChild(wrap);
  }
  return stage;
}

function buildParticles() {
  const stage = document.createElement('div');
  stage.className = 'particles-stage';

  const N = 18;
  for (let i = 0; i < N; i++) {
    const s     = document.createElement('div');
    s.className = 'streak';
    const top   = 5  + Math.random() * 85;
    const left  = -10 + Math.random() * 80;
    const len   = 36 + Math.random() * 90;
    const isOrg = Math.random() > 0.45;
    const color = isOrg ? 'var(--orange)' : 'var(--teal)';
    const dur   = (1.8 + Math.random() * 2.4).toFixed(2);
    const dly   = (-(Math.random() * 3)).toFixed(2);
    s.style.cssText = `
      top:${top}%; left:${left}%;
      width:${len}px;
      background: linear-gradient(90deg, ${color}, transparent);
      animation-duration:${dur}s;
      animation-delay:${dly}s;
    `;
    stage.appendChild(s);
  }
  return stage;
}

// ── UI state machine ────────────────────────────────────────────────────────

function setUiState(state) {
  uiState = state;

  // -- visual frame gradient border --
  visualFrame.className =
    'visual-frame' +
    (state === 'recording'  ? ' recording'   :
     state === 'processing' ? ' transcribing' : '');

  // -- visual area content --
  visualArea.innerHTML = '';

  if (state === 'idle') {
    visualArea.appendChild(buildIdle());
  } else if (state === 'recording') {
    visualArea.appendChild(buildWaveform());
  } else if (state === 'processing') {
    visualArea.appendChild(buildTranscribing());
  }

  // -- header dot --
  headerDot.className = 'header-dot';
  if (state === 'idle') {
    headerDot.classList.add('teal');
  } else {
    headerDot.classList.add('pulse');
  }

  // -- status text --
  statusTag.classList.remove('visible');
  switch (state) {
    case 'idle':
      statusMsg.textContent = 'Hold the logo to record';
      break;
    case 'recording':
      statusMsg.textContent = 'Recording\u2026 (Listening for speech)';
      break;
    case 'processing':
      statusMsg.textContent = 'Transcribing\u2026';
      break;
  }
}

// ── Textarea helpers ────────────────────────────────────────────────────────

function updateCopyState() {
  const n = transcript.value.trim().length;
  copyBtn.disabled = n === 0;
  charCount.textContent = n > 0 ? n + '\u202fchars' : '';
}
transcript.addEventListener('input', updateCopyState);

copyBtn.addEventListener('click', async () => {
  const text = transcript.value.trim();
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copyBtn.innerHTML = '\u2713\u00a0Copied!';
    copyBtn.classList.add('success');
    setTimeout(() => {
      copyBtn.innerHTML = COPY_HTML;
      copyBtn.classList.remove('success');
    }, 1600);
  } catch (_) {}
});

// ── Audio helpers ───────────────────────────────────────────────────────────

function resample(data, fromRate, toRate) {
  if (fromRate === toRate) return data;
  const ratio     = fromRate / toRate;
  const newLength = Math.round(data.length / ratio);
  const out       = new Float32Array(newLength);
  for (let i = 0; i < newLength; i++) {
    const pos = i * ratio;
    const idx = Math.floor(pos);
    const a   = data[idx] ?? 0;
    const b   = data[Math.min(idx + 1, data.length - 1)];
    out[i] = a + (pos - idx) * (b - a);
  }
  return out;
}

// ── Recording ───────────────────────────────────────────────────────────────

async function startRecording() {
  if (recording) return;

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch {
    statusMsg.textContent = 'Microphone blocked \u2014 allow access in the address bar';
    return;
  }

  audioCtx   = new (window.AudioContext || window.webkitAudioContext)();
  sourceNode = audioCtx.createMediaStreamSource(mediaStream);
  processor  = audioCtx.createScriptProcessor(4096, 1, 1);
  silentGain = audioCtx.createGain();
  silentGain.gain.value = 0;

  chunks    = [];
  recording = true;

  processor.onaudioprocess = (e) => {
    if (recording) chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };

  sourceNode.connect(processor);
  processor.connect(silentGain);
  silentGain.connect(audioCtx.destination);

  setUiState('recording');
  transcript.value = '';
  updateCopyState();
}

async function stopRecording() {
  if (!recording) return;
  recording = false;

  setUiState('processing');

  processor.disconnect();
  sourceNode.disconnect();
  silentGain.disconnect();
  mediaStream.getTracks().forEach(t => t.stop());
  const nativeRate = audioCtx.sampleRate;
  audioCtx.close();

  const totalLen = chunks.reduce((s, c) => s + c.length, 0);
  const full     = new Float32Array(totalLen);
  let offset = 0;
  for (const c of chunks) { full.set(c, offset); offset += c.length; }

  const audio16k = resample(full, nativeRate, TARGET_RATE);

  try {
    const res  = await fetch('/transcribe', {
      method:  'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body:    audio16k.buffer,
    });
    const data = await res.json();

    if (data.text) {
      transcript.value = data.text;
      updateCopyState();
      try { await navigator.clipboard.writeText(data.text); } catch (_) {}
      setUiState('idle');
    } else {
      setUiState('idle');
      statusMsg.textContent = data.error || 'No speech detected \u2014 try again';
    }
  } catch {
    setUiState('idle');
    statusMsg.textContent = 'Server error \u2014 is the server still running?';
  }
}

// ── Input events ─────────────────────────────────────────────────────────────

// Recording starts only when the idle logo is held (mouse or touch).
// Release anywhere on the page stops it so the finger/pointer doesn't need
// to return to the logo before the transcription request is sent.
visualArea.addEventListener('mousedown', e => {
  if (uiState !== 'idle') return;
  e.preventDefault();
  startRecording();
});
document.addEventListener('mouseup', () => stopRecording());

visualArea.addEventListener('touchstart', e => {
  if (uiState !== 'idle') return;
  e.preventDefault();
  startRecording();
}, { passive: false });
document.addEventListener('touchend', () => stopRecording(), { passive: false });

// ── Boot: render idle visual ─────────────────────────────────────────────────
setUiState('idle');
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/logo":
            try:
                data = _LOGO_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
            return

        body = _HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/transcribe":
            length = int(self.headers.get("Content-Length", 0))
            raw    = self.rfile.read(length)

            if not raw:
                self._json({"text": "", "error": "No audio received"})
                return

            audio    = np.frombuffer(raw, dtype=np.float32).copy()
            duration = len(audio) / 16000

            if duration < _min_recording_seconds:
                self._json({"text": "", "error": "Silence or too short — try again"})
                return

            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < _silence_rms_threshold:
                self._json({"text": "", "error": "Silence or too short — try again"})
                return

            text = _transcriber.transcribe(audio)

            if text:
                try:
                    import pyperclip
                    pyperclip.copy(text)
                except Exception:
                    pass

            self._json({"text": text})

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data: dict):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _transcriber, _silence_rms_threshold, _min_recording_seconds

    cfg = json.loads(CONFIG_PATH.read_text())
    _silence_rms_threshold = cfg.get("silence_rms_threshold", 0.01)
    _min_recording_seconds = cfg.get("min_recording_seconds", 0.5)

    _transcriber = Transcriber(
        model_size=cfg.get("model_size", "base"),
        device=cfg.get("device", "cpu"),
        compute_type=cfg.get("compute_type", "int8"),
        language=cfg.get("language"),
    )

    print("Loading Whisper model (first run may download ~150 MB)…", flush=True)
    _transcriber.transcribe(np.zeros(16000, dtype=np.float32))
    print(f"Ready.  Open → http://localhost:{PORT}", flush=True)
    print("Hold Spacebar or hold anywhere on the widget to dictate. Ctrl+C to quit.\n",
          flush=True)

    server = http.server.HTTPServer(("127.0.0.1", PORT), _Handler)
    webbrowser.open(f"http://localhost:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")
        server.shutdown()


if __name__ == "__main__":
    main()
