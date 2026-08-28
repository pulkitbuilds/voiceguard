# Deploying VoiceGuard to Vercel

This folder is structured for a direct Vercel deploy:

```
voiceguard-vercel/
├── vercel.json
├── public/
│   └── index.html          ← the dashboard (fully client-side, no backend needed)
└── api/
    ├── index.py             ← FastAPI serverless function: GET /api/health, POST /api/analyze
    ├── lite_features.py      ← numpy/scipy-only feature extraction (no librosa)
    ├── risk_engine.py
    └── requirements.txt
```

## Important limitation first

Vercel serverless functions are **request/response only** — no persistent connections. That
means the `/stream` WebSocket endpoint from the full backend (`/backend` in the main project,
used for live near-real-time call analysis) **cannot run on Vercel**. This deploy gives you:

- The full interactive dashboard (works exactly as before — it does all analysis in-browser).
- A one-shot `POST /api/analyze` REST endpoint (upload a recording, get a risk report back) —
  good for analyzing call recordings, voicemails, or IVR samples after the fact.

For true live-call streaming analysis, deploy `/backend` (the librosa version with `/stream`)
on a platform that supports long-lived processes — Render, Railway, Fly.io, or a plain VM —
and point any production integration at that instead. Vercel and that backend can coexist:
dashboard + REST demo on Vercel, streaming service elsewhere.

## Option A — Deploy with the Vercel CLI (fastest)

```bash
npm install -g vercel        # one-time
cd voiceguard-vercel
vercel login                 # opens a browser to authenticate
vercel                       # deploys a preview; follow the prompts
vercel --prod                # promote to production once you're happy
```
Vercel will detect `vercel.json`, build the Python function in `api/`, and serve `public/`
as static files. You'll get a `https://<project>.vercel.app` URL immediately.

## Option B — Deploy via GitHub + the Vercel dashboard

1. Push this folder to a GitHub repo:
   ```bash
   cd voiceguard-vercel
   git init && git add . && git commit -m "VoiceGuard initial deploy"
   git branch -M main
   git remote add origin https://github.com/<you>/voiceguard.git
   git push -u origin main
   ```
2. Go to https://vercel.com/new, import that repo.
3. Framework preset: choose "Other" (this isn't Next.js/etc — `vercel.json` handles routing).
4. Leave build/output settings default — `vercel.json` already specifies the Python build.
5. Deploy. Vercel gives you a production URL and auto-redeploys on every push to `main`.

## After deploying

- Dashboard: `https://<your-project>.vercel.app/`
- Health check: `https://<your-project>.vercel.app/api/health`
- Analyze a file:
  ```bash
  curl -F "file=@sample.wav" https://<your-project>.vercel.app/api/analyze
  ```

## Things worth tightening before real use

- **CORS**: `api/index.py` currently allows `allow_origins=["*"]`. Restrict this to your
  dashboard's actual domain once deployed.
- **Cold starts**: Python serverless functions on Vercel have cold-start latency (typically
  1–3s on the Hobby tier). If you need consistently low latency, look at Vercel's "Fluid
  compute" / always-warm options, or keep this REST endpoint on a always-on host instead.
- **File size / timeouts**: Hobby-tier functions have a request body size limit (~4.5MB) and
  execution timeout (10s by default, extendable on Pro). Long recordings should be chunked
  client-side or analyzed via the full `/backend` service instead.
- **Env vars / secrets**: if you add API-key auth, set it via `vercel env add` rather than
  hardcoding it.
