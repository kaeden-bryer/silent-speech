# Frontend (track 1)

**Job:** the app people actually use. It has to work in any browser: iPhone Safari, Android Chrome, laptops.

**Contract:** every backend call lives in [js/api.js](js/api.js). The endpoints are listed in the [root README](../README.md#http-api-frontend--backend), with live docs at `<backend>/docs`.

**Current state:** `index.html` and `js/main.js` are a bare test page so the team can try the pipeline. Replace them freely, with any framework you like. Just keep api.js as the one place that talks to the backend.

## Run

The backend serves this folder at http://localhost:8000. To serve it some other way (Live Server, Vite, Vercel…), point it at a backend once with `?api=http://localhost:8000` (or a tunnel URL). The setting is remembered in that browser.

## Things the real UI needs to handle

- **Playing results:** if `audio_url` is set, play it. If it's `null`, speak `text` with `speechSynthesis` (the emotion can map to pitch and rate).
- **Placeholders:** `/api/health` lists the modules with `fallback: true`. For example, hide the call UI while telephony is a placeholder.
- **Conversation log:** `GET /api/session/{id}`. Poll it during a call: the other person's words arrive as `"other"` turns.
- **Phone quirks:**
  - The camera needs HTTPS (see the root README for tunnels).
  - iOS only plays audio after a tap: unlock it on the first tap.
  - iOS records mp4, other browsers record webm. The backend accepts both.
  - Add `playsinline` to the `<video>` element.
- **Typing as a backup:** `POST /api/utterance/text` works even when lip reading is a placeholder.
