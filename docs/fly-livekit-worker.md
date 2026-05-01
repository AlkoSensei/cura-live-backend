# Fly.io: LiveKit agent worker

Use this when you want the **worker** on Fly and the **HTTP API** elsewhere (e.g. Render). Run **only one** worker fleet (Fly **or** Render background worker) with the same `LIVEKIT_AGENT_NAME`.

## One-time

1. Install CLI: [Fly.io install](https://fly.io/docs/hands-on/install-flyctl/).
2. Login: `flyctl auth login`
3. Create the app (name must match `fly.toml` → `app`, or edit `fly.toml` after creation):

   ```bash
   flyctl apps create kare-live-livekit-worker --org personal
   ```

4. Set **secrets** (minimum for LiveKit + agent pipeline — mirror your Render/API env):

   ```bash
   flyctl secrets set \
     LIVEKIT_URL="wss://YOUR_PROJECT.livekit.cloud" \
     LIVEKIT_API_KEY="..." \
     LIVEKIT_API_SECRET="..." \
     LIVEKIT_AGENT_NAME="kare-appointment-agent" \
     SUPABASE_URL="..." \
     SUPABASE_SERVICE_ROLE_KEY="..." \
     DEEPGRAM_API_KEY="..." \
     SARVAM_API_KEY="..." \
     ANTHROPIC_API_KEY="..."
   ```

   Add optional keys when used (same as `.env.example` / Render):

   - `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`
   - `LIVEKIT_AVATAR_PROVIDER`, `BEY_*`, `TAVUS_*`
   - `DEEPGRAM_MODEL`, `DEEPGRAM_LANGUAGE`, `SARVAM_*`, `CLAUDE_MODEL`, etc.

5. Deploy:

   ```bash
   flyctl deploy --remote-only
   ```

6. Logs:

   ```bash
   flyctl logs
   ```

## CI/CD (GitHub)

1. Fly dashboard → **Tokens**: create a deploy token.
2. GitHub repo → **Settings → Secrets → Actions** → add `FLY_API_TOKEN`.
3. Push to `main` (or run workflow manually). Workflow file: `.github/workflows/fly-livekit-worker.yml`.

## Notes

- `Dockerfile.worker` runs `python -m app.agent.run_worker start` (LiveKit’s CLI requires the `start` subcommand); image uses Python 3.11 to match `Dockerfile`.
- Primary region is `sin` in `fly.toml`; change `primary_region` if needed.
- If `render.yaml` still defines `kare-live-livekit-worker` **Render background worker**, delete or disable that service before relying on Fly, or you will register **two** workers.
