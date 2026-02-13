---
name: TikTok Demo Video Generator
overview: Build a Python script that generates a professional MP4 demo video with AI voice narration (echo voice via Azure OpenAI Mini TTS) showing the full Sovereign Sanctuary onboarding flow followed by the end-to-end TikTok integration, for submission to TikTok's developer app review.
todos:
  - id: install-deps
    content: Install moviepy (pulls in imageio-ffmpeg for MP4 encoding)
    status: completed
  - id: build-script
    content: Create tools/generate_tiktok_demo.py with all 16 slide render functions, TTS narration generation (echo voice), transitions, and video+audio assembly
    status: completed
  - id: generate-video
    content: Run the script to produce tools/tiktok_demo.mp4 (with audio) and verify output
    status: completed
isProject: false
---

# TikTok Developer Review Demo Video (MP4 with AI Voice Narration)

## Goal

Generate a polished MP4 video (~70-90s) with **Little Nate's "echo" voice narrating each slide** via Azure OpenAI Mini TTS. TikTok's review team watches this to understand the complete integration. The video shows:

1. The app's 7-step client onboarding tutorial (the user's first experience)
2. The end-to-end TikTok integration flow (OAuth connect, content creation, posting, moderation)

## Dependencies

Install `moviepy` (which bundles `imageio-ffmpeg` for MP4 encoding):

```bash
pip install moviepy
```

- **Pillow** (already installed at v11.3.0) -- frame/image generation
- **httpx** (already installed) -- Azure OpenAI Mini TTS REST calls
- **moviepy** (to install) -- video assembly + audio merging

## Audio Narration (Echo Voice)

Each slide gets a narration script spoken by the **"echo"** voice via Azure OpenAI Mini TTS REST API.

### TTS API Call Pattern

Uses the same endpoint as [bridge_server.py](backend/app/websocket/bridge_server.py) line 373:

```
POST https://{AZURE_OPENAI_ENDPOINT}/openai/deployments/gpt-4o-mini-tts/audio/speech?api-version=2025-01-01-preview

Headers: api-key: {AZURE_API_KEY}
Body: {"model": "gpt-4o-mini-tts", "input": "<narration text>", "voice": "echo", "response_format": "mp3"}

Response: raw MP3 bytes
```

Credentials read from `.env`: `AZURE_API_KEY` and `AZURE_OPENAI_ENDPOINT`.

### Narration Script (per slide)

- Slide 1 (Title): "Welcome to Sovereign Sanctuary. An AI-powered therapeutic platform, powered by Little Nate."
- Slide 2 (Welcome Gate): "When users first open the app, they're greeted by Little Nate -- their AI therapy companion. This is the welcome gate where the guided tour begins."
- Slide 3 (Chat): "Users can chat with Nate through a secure text interface. Every conversation is private, encrypted, and clinically informed."
- Slide 4 (Voice Mode): "Nate also offers real-time voice sessions with emotional analysis, powered by Azure OpenAI's realtime voice API."
- Slide 5 (Metrics): "The Nevedal Coherence Engine tracks emotional growth over time, providing users with meaningful insights into their therapeutic journey."
- Slide 6 (Avatar): "Avatar mode gives Nate a visual presence, creating a more immersive companion experience."
- Slide 7 (Family): "Family Sanctuary connects the whole family in a shared therapeutic space, with individual privacy preserved."
- Slide 8 (Tiers): "Users choose their tier -- from the free Threshold trial, to Inner Chamber, to the premium Sovereign Circle."
- Slide 9 (SkyEye): "Now let's look at the TikTok integration. From the SkyEye dashboard, administrators connect Little Nate to TikTok."
- Slide 10 (OAuth): "The OAuth flow requests specific scopes: user info, video publishing, and comment management. Users authorize securely through TikTok's own consent screen."
- Slide 11 (Connected): "Once connected, the dashboard shows live stats -- followers, engagement rate, and post count -- all pulled from the TikTok API."
- Slide 12 (Content): "Little Nate generates TikTok-optimized content using AI -- short, punchy, visual-first -- matching TikTok's native voice while staying clinically appropriate."
- Slide 13 (Queue): "Generated content enters a review queue. Administrators can approve, edit, schedule, or reject posts before they go live."
- Slide 14 (Publish): "Approved content is published through TikTok's Content Posting API with proper AIGC disclosure labels, as required by TikTok policy."
- Slide 15 (Moderation): "Inbound comments are monitored in real-time. Bot detection, cyberbullying filters, and an enforcement ladder keep the community safe."
- Slide 16 (End): "Sovereign Sanctuary and TikTok -- building a safer, more connected therapeutic community. Visit app.sovereignsanctuary.net."

### Audio Generation Flow

1. For each slide, call the Mini TTS endpoint with the narration text
2. Save each as `tools/audio/slide_{n}.mp3`
3. Measure duration of each MP3 -- this determines each slide's display time (audio length + 0.5s padding)
4. Concatenate all audio clips into a single track
5. Merge audio track with the video frames using moviepy

## Video Structure (16 slides, duration driven by narration)

### Part 1: Onboarding Welcome (slides 1-8)

Each slide is a 1920x1080 frame rendered by Pillow using the app's design system (#050505 background, #C9A962 gold, #4ECDC4 cyan, DM Sans / Cormorant Garamond fonts).

- Slide 1: **Title card** -- "Sovereign Sanctuary" logo, app URL, "Powered by Little Nate AI"
- Slide 2: **Welcome Gate** -- Nate orb graphic, "Welcome to the Sanctuary", BEGIN TOUR button
- Slide 3: **Chat with Nate** -- Mockup of chat interface, message bubbles
- Slide 4: **Voice Mode** -- Microphone icon, waveform visual
- Slide 5: **Emotional Metrics** -- CEE gauge graphic, coherence indicators
- Slide 6: **Avatar Mode** -- Nate avatar representation
- Slide 7: **Family Sanctuary** -- Family tree graphic, connected care
- Slide 8: **Tier Selection** -- Three pricing tiers (Threshold / Inner Chamber / Sovereign Circle)

### Part 2: TikTok Integration (slides 9-15)

- Slide 9: **SkyEye Dashboard** -- Platform grid showing TikTok card with "Connect" button
- Slide 10: **OAuth Flow** -- TikTok authorization screen mockup, scopes listed
- Slide 11: **Connected** -- TikTok card green, stats visible
- Slide 12: **Content Creation** -- AI content generator with TikTok selected
- Slide 13: **Content Queue** -- Draft TikTok post ready for review/approval
- Slide 14: **Publishing** -- Post published confirmation, AIGC compliance label
- Slide 15: **Moderation** -- Comment monitoring, bot detection, enforcement ladder

### Closing

- Slide 16: **End card** -- "Sovereign Sanctuary x TikTok", app URL, contact

## Technical Approach

### Single script: `tools/generate_tiktok_demo.py`

1. **TTS generation** -- For each slide, call Azure OpenAI Mini TTS REST endpoint with voice "echo" and the narration script. Save MP3 files to `tools/audio/`. Read `AZURE_API_KEY` and `AZURE_OPENAI_ENDPOINT` from `.env` using dotenv.
2. **Frame generation** -- Each slide is a function that uses `PIL.Image` + `PIL.ImageDraw` + `PIL.ImageFont` to render a 1920x1080 frame:
  - App's dark theme (#050505 base, #111111 cards)
  - Gold (#C9A962) headers and accents
  - Cyan (#4ECDC4) for AI/TikTok interaction elements
  - Rounded card panels, progress indicators
  - Icon representations drawn with shapes (circles, rectangles, lines)
  - Step numbers and descriptive captions
3. **Duration sync** -- Each slide's display duration matches its audio clip length + 0.5s padding
4. **Transitions** -- Simple fade-in/fade-out between slides (generate intermediate alpha-blended frames)
5. **Assembly** -- Use moviepy to:
  - Create an ImageClip per slide with its calculated duration
  - Concatenate all clips with crossfade transitions
  - Load all MP3 narration clips and concatenate into one AudioFileClip
  - Set the audio track on the video
  - Write final MP4 (H.264 video, AAC audio)
6. **Output** -- `tools/tiktok_demo.mp4` (1920x1080, H.264 + AAC, ~70-90s)

### Font handling

- Try to load system fonts (DM Sans, Cormorant Garamond) via `PIL.ImageFont.truetype`
- Fall back to similar system fonts (Helvetica, Arial, Georgia) if not available
- Final fallback to Pillow's default font

## File output

- Script: `tools/generate_tiktok_demo.py`
- Audio clips: `tools/audio/slide_01.mp3` through `slide_16.mp3` (intermediate, can delete after)
- Video: `tools/tiktok_demo.mp4` (final output with echo voice narration)

## Execution

```bash
pip install moviepy
python tools/generate_tiktok_demo.py
```

The resulting `tools/tiktok_demo.mp4` is the file to upload to TikTok's developer portal under "Demo Video."