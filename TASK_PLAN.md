# J.A.R.V.I.S - Heavy-Duty Coding Agent Upgrade

## Changes Implemented

### 1. New Google AI SDK (`google-genai`) + Context Caching
- **Problem**: Old `google.generativeai` SDK import failed with `No module named 'google.generativeai'`
- **Fix**: Install `google-genai` package and use `from google import genai` / `from google.genai import types`
- **New**: `JarvisAgentBrain` class with:
  - Google API Key Rotation (multiple keys, seamlessly swaps on 429/rate-limit)
  - Context Caching - upload codebase once, cache for hours, subsequent queries only consume new tokens
  - Automatic fallback to Groq when all Google keys exhausted

### 2. Natural Voice Activity Detection (VAD) - Fixed Listening
- **Problem**: Response was too fast, cutting off user mid-sentence because of arbitrary timeouts
- **Fix**: 
  - Event-driven listening with proper silence detection (not time-based)
  - Dynamic energy threshold calibrated per utterance
  - Waits for natural speech pause (1.5s of silence = end of speech)
  - Processes entire utterance without truncation
  - Continuous voice stream analysis using sounddevice

### 3. Multi-Key .env Support
- Added `GEMINI_API_KEY_2` to `.env.example`
- Updated `.env` with second key slot

### 4. No Auto-Push to GitHub
- Verified `.gitignore` already protects `.env` and generated files
- No auto-commit/push logic in codebase