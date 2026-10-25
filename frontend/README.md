# Frontend (track 1)

One responsive web app for phones and computers: Vite + React + Tailwind, Andx-inspired design (dark/light, orange accent). Currently static mockup screens — mock data mirrors the backend shapes, and every backend call goes through [src/api.js](src/api.js).

- `src/App.jsx` — screen switcher (`#welcome` / `#chat` / `#live` deep-links) + dark/light toggle
- `src/screens/` — Welcome, Conversation (sidebar/drawer + chat), LiveCapture (camera + record)
- `src/components/ui.jsx` — Avatar, Logo, EmotionChip, icons
- `src/index.css` — theme palette (colors, font)
- `test.html` — the bare backend test page, kept for quick pipeline checks

## Develop

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173, /api proxied to localhost:8000
```

On a phone, camera needs HTTPS: `cloudflared tunnel --url http://localhost:5173` and open the printed URL.

## Demo through the backend

`npm run build` outputs `dist/`; the backend serves it at http://localhost:8000 (falls back to this folder if `dist/` doesn't exist). Then tunnel port 8000 as in the root README.
