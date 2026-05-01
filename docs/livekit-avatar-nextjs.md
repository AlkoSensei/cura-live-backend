# Next.js frontend handoff

Backend API prefix is **`/api`** (see `api_prefix` in settings). All paths below are relative to your backend origin, for example `https://your-api.example.com/api/...`.

---

## LiveKit + Beyond Presence avatar

When the backend has `LIVEKIT_AVATAR_PROVIDER=bey` and `BEY_API_KEY` set, the Python worker joins a Beyond Presence avatar participant and routes synthesized speech to it. The HTTP session response tells the UI whether to render that participant.

### `POST /livekit/sessions`

Response fields:

| Field | Meaning |
|-------|---------|
| `avatar_enabled` | `true` when Beyond Presence avatar is active |
| `avatar_provider` | `"bey"` or `null` |
| `avatar_participant_identity` | Subscribe/render the remote participant with this **identity** (defaults to `kare-avatar-agent` unless overridden via env) |

Connect with `livekit_url`, `token`, and `room_name` as before.

### Frontend behavior

1. **Subscribe** to all remote participants as usual.
2. When `avatar_enabled` is `true`:
   - Find the participant whose `identity === avatar_participant_identity` from the API response.
   - Attach their **camera** track to your video element (or `@livekit/components-react` `VideoTrack`).
   - Play **audio** from that same participant only for agent speech. Do **not** attach/play audio from the primary LiveKit agent participant (duplicate voice).
3. When `avatar_enabled` is `false`: keep your existing behavior (audio from the agent participant).
4. Keep publishing the **user microphone** unchanged.

### Loading / interruption UX

- Until the avatar participant publishes video, show a spinner or your existing audio-only visualizer.
- Interruptions are coordinated by LiveKit Agents + the avatar plugin; avoid deriving conversation state from video frames—use agent/user state events if you already consume them over SSE.

### Manual verification (avatar)

- Exactly **one** audible agent voice.
- Lip sync follows speech from your existing Sarvam TTS pipeline.
- Speaking over the agent clears or updates avatar playback without stuck audio.

---

## Appointment history (paginated + search)

Returns **every** appointment in the system (newest slot first). Narrow the table with **`search`** (patient name or phone substring)—there is no separate `phone_number` query parameter.

### `GET /appointments/history`

**Query parameters**

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `page` | no | `1` | Page index (1-based). |
| `page_size` | no | `20` | Page size (max `100`). |
| `search` | no | — | Case-insensitive substring on **patient name** or **phone number** (max 120 chars). `%`, `_`, and `,` are stripped from input for safety. |
| `status` | no | *(omit)* | Filter: `booked`, `cancelled`, or `completed`. Omit to return **all** statuses. |

**Response** (`PaginatedAppointments`)

| Field | Type | Description |
|-------|------|-------------|
| `items` | `Appointment[]` | Rows for this page, sorted by **appointment date/time descending** (newest slot first). |
| `total` | `number` | Total rows matching filters (all pages). |
| `page` | `number` | Current page. |
| `page_size` | `number` | Requested page size. |

**Examples**

```http
GET /api/appointments/history?page=1&page_size=20
GET /api/appointments/history?page=1&page_size=20&search=Asha
GET /api/appointments/history?page=1&page_size=20&search=98765
```

**Next.js notes**

- Drive the table from `items`; compute `totalPages = Math.ceil(total / page_size)` for pagination controls.
- Debounce the search input (e.g. 300 ms) before refetching with `page=1`.
- Use `search` for name or phone filters (e.g. digits-only phone fragment works against stored `phone_number`).
- Optionally pass `status=booked` for an “upcoming only” view and omit `status` for full history.

---

## Cancel appointment

Two equivalent ways to cancel (same validation: appointment must exist, belong to `phone_number`, and not already cancelled).

### `DELETE /appointments/{appointment_id}`

**Query parameters**

| Name | Required | Description |
|------|----------|-------------|
| `phone_number` | yes | Must match the appointment owner. |

**Example**

```http
DELETE /api/appointments/550e8400-e29b-41d4-a716-446655440000?phone_number=%2B919876543210
```

Response body: updated `Appointment` with `status: "cancelled"`.

Errors: `404` if not found, `403` if phone does not match, `400` with message if already cancelled.

### `POST /appointments/cancel` (existing)

JSON body: `{ "appointment_id": "<uuid>", "phone_number": "<string>" }` — keep using this from forms if you prefer POST.

**Next.js notes**

- Prefer **`DELETE`** from the history row action for REST semantics and simpler caching (`invalidateQueries` after success).
- Refresh the history query (or optimistically remove/update the row) after a successful cancel.
