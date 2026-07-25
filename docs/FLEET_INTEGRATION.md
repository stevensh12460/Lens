# Fleet Communication & Integration — verified state, 2026-07-24

Handoff document for whoever is planning the full project integration.
**Everything below was measured on the live machines today, not assumed.**
Where something is uncertain or unverified, it says so.

---

## 1. The fleet

Private LAN, subnet `192.168.158.0/24`, gateway `.1`. Steven considers this LAN
trusted. All four machines are powered on and reachable.

| host | IP | OS | user | role |
|---|---|---|---|---|
| **Mac Studio** | `.123` (en0), `.216` (en1) | macOS 25.5 | `stevenhoward` | The services box. LENS, El Jefe, Kitchen Window shim, Ollama |
| **New Box** | `.107` | Ubuntu (`omnissiah-MS-7B48`) | `omnissiah` | Runs **ATLAS** — daemon + chat server, systemd *user* unit |
| **GGcomp** | `.237` | Windows | `steve` | Dev box. `D:/ATLAS` is the ATLAS source of truth; deploys go from here |
| **TheOmnissiah** | `.203` | **Windows 11** | `TheOm` | Ollama secondary. Note: Windows, not Linux |
| iPhone | `.233` | iOS | — | On the same LAN. Reaches services directly, no tunnel needed at home |

---

## 2. SSH — full mesh, working

**Mac's key:** `~/.ssh/fleet_mac` (deliberately NOT the default `id_ed25519`)
fingerprint `SHA256:17IvEd4KBkQwl9/E38ntyfV63oSEWSPOTe8zKmSzUkc`
Deployed to all three other boxes.

**GGcomp's key:** `SHA256:jnUzwIPIRQX6do1Qb7Ns3pM8y6HBe7+YqGqGSYz6PVc`
(`steve@GGcomp`), installed in the Mac's `~/.ssh/authorized_keys`.

**Aliases** in the Mac's `~/.ssh/config` — `ssh newbox`, `ssh ggcomp`,
`ssh omnissiah`. Each pins `fleet_mac` with `IdentitiesOnly yes`.

Verified outbound from the Mac:
```
ssh ggcomp     -> GGcomp
ssh newbox     -> omnissiah-MS-7B48
ssh omnissiah  -> TheOmnissiah
```

### SSH gotchas that cost real time

1. **`IdentitiesOnly yes` is mandatory here.** The Mac also holds a GitHub deploy
   key. Without this, ssh offers it first and authenticates as the wrong identity.
2. **macOS sshd is socket-activated.** `launchctl print system/com.openssh.sshd`
   reports `state = not running` even when SSH works perfectly. Check port 22,
   never the service state.
3. **Two boxes are Windows.** Default SSH shell is `cmd.exe`, so `;` is NOT a
   command separator — `ssh host 'echo A; whoami'` echoes the string back
   verbatim. Send one command per invocation, or invoke powershell explicitly.
4. **Windows admin accounts ignore `~/.ssh/authorized_keys`** entirely and read
   only `C:\ProgramData\ssh\administrators_authorized_keys`. Silent
   permission-denied with no hint. This is the single most common failure.

---

## 3. Services on the Mac — and what is LAN-reachable

| port | service | binds | LAN-reachable | launchd (survives reboot) |
|---|---|---|---|---|
| 8600 | **LENS API** (FastAPI) | `*` | **yes** | `com.lens.core` |
| 8800 | **LENS dashboard** | `*` | **yes** | `com.lens.dashboard` |
| 7900 | **El Jefe** draft server | `*` | **yes** | `com.steven.eljefe.draft` |
| 9000 | Kitchen Window shim | `127.0.0.1` | **no** | manual process |
| 11434 | Ollama | `127.0.0.1` | **no** | `com.lens.ollama` |

Other LENS launchd units: `com.lens.watcher`, `com.lens.backup`,
`com.lens.post-scheduler`, `com.lens.token-monitor`.

**Binding is the thing that actually gates integration, not the network.** A
service on `127.0.0.1` is invisible to the fleet no matter how good the LAN is.
El Jefe was in exactly that state until today — see §5.

---

## 4. Verified connectivity matrix

Measured **from New Box** (where ATLAS runs), reaching the Mac:

```
El Jefe      http://192.168.158.123:7900/health          200
LENS API     http://192.168.158.123:8600/pipeline/health 200
LENS dash    http://192.168.158.123:8800/                200
KW shim      http://192.168.158.123:9000/                --- unreachable (binds localhost)
Mac Ollama   http://192.168.158.123:11434/api/tags       --- unreachable (binds localhost)
```

Ollama endpoints across the fleet:
- New Box (local): `nomic-embed-text`, `qwen2.5:7b`
- GGcomp `.237`: `qwen3:14b`, `qwen3:14b-hermes`, `qwen2.5-coder:14b`, `gemma2:9b`, `llama3.1:8b-instruct-q5_K_M`
- TheOmnissiah `.203`: reachable on 11434, model list not enumerated
- Mac `.123`: **not reachable** — binds localhost

---

## 5. ATLAS

Lives at `~/atlas` on New Box. **systemd user unit**, currently `active`.
Requires `loginctl enable-linger omnissiah` to survive logout/reboot.
Standalone by design: own SQLite (`data/atlas.db`), no shared DB, no message bus.

Chat server on **:8765**, reachable across the LAN, **token-protected**.
An unauthenticated request returns `403 {"detail":"forbidden"}` — **that is
healthy, not broken.** `ATLAS_CHAT_TOKEN` is set.

Live config on New Box:
```
ATLAS_DEFAULT_MODEL_ENDPOINT   = http://localhost:11434        # New Box's own
ATLAS_SECONDARY_MODEL_ENDPOINT = http://192.168.158.203:11434  # TheOmnissiah
ATLAS_ELJEFE_BASE_URL          = http://192.168.158.123:7900   # the Mac  ← set today
ATLAS_ELJEFE_TENANT            = steven                        # see §6
ATLAS_CHAT_TOKEN               = <set>
```

### What was fixed today
El Jefe bound `127.0.0.1` on both 7800 and 7900, so **no value of
`ATLAS_ELJEFE_BASE_URL` could ever have worked** from another machine. The LAN
was necessary but not sufficient. Changes:

- added `EL_JEFE_HOST` env to `src/el_jefe/config.py` (`server_host`),
  **default still `127.0.0.1`** so nothing is exposed by accident;
- `api/draft_server.py` and `chat/server.py` now bind `settings.server_host`;
- new `~/Library/LaunchAgents/com.steven.eljefe.draft.plist` sets
  `EL_JEFE_HOST=0.0.0.0` with `KeepAlive`. **That server was previously a manual
  process that died on every reboot.**

---

## 6. El Jefe — and an important conceptual correction

Live state: 5 tenants, all **documentary subjects**.
```
default(3 seg)  chef_mark(81)  david_cruz(107)  eric_gm(89)  keshonn(58)
```

Routes: `GET /health /tenants /chefs /persona`,
`POST /draft_reply /generate_caption /persona/build /persona/feed
/voice_match_score /archive_coverage_check`.

**Correction from Steven, and it matters for planning:** El Jefe's tenants are
*subjects it holds material about*. **Steven is the operator, not a subject.**

So `ATLAS_ELJEFE_TENANT=steven` — and the hard-coded `steven` tenant in ATLAS's
`eljefe_client.py`, described there as "safety invariant §9.1, the tenant wall" —
encodes an assumption that does not match how the system is actually used. There
is no `steven` tenant and, per Steven, there shouldn't need to be one.

**Open question for the integration owner:** what does ATLAS actually want from
El Jefe? If it's to query the *subjects* while working, the tenant wall needs
rethinking, because it locks to `steven` and accepts no tenant argument. Do not
"fix" this by provisioning a `steven` tenant without deciding that first.

Steven's framing: *"steven is not a tenant of it but a user, and ATLAS is his
experience."*

---

## 7. LENS (the Mac)

FastAPI on 8600, dashboard 8800, SQLite at `~/lens/data/lens.db` (399,970 image
rows). Already binds `*`, so it has been LAN-reachable from the moment the Mac
joined. Integrates with Lightroom Classic via a custom plugin.

Also built today, relevant to integration surface:
- `/web/*` endpoints that publish photos from Lightroom to the live website
  (`stevenhowardphotography.com`, Cloudflare Pages, git push via a repo-scoped
  SSH deploy key at `~/.ssh/lens_shp_site`)
- kill switch `~/lens/WEB_PUBLISH_DISABLED`
- existing Instagram publishing with kill switch `~/lens/AUTO_PUBLISH_DISABLED`

**No authentication on LENS.** Anything on the LAN can read the database, trigger
pipeline runs, and push to the live website. Deliberate — single-user by design —
but the threat model changed the moment the Mac joined the LAN, and the
integration owner should decide whether that stays true.

---

## 8. State summary

**Working**
- Full-mesh SSH, all four machines, verified in both directions
- ATLAS daemon active on New Box
- ATLAS → El Jefe reachable (200) and configured
- ATLAS → LENS reachable (200), not yet used
- El Jefe survives reboots for the first time

**Not connected**
- Mac's Ollama — binds localhost, so the fleet cannot use the Mac's GPU
- Kitchen Window shim — binds localhost
- ATLAS ↔ LENS — the wire is open, nothing flows over it yet
- `loginctl enable-linger` on New Box — **unverified**, ATLAS may not survive a reboot

**Decisions needed**
1. The `steven` tenant question (§6) — blocks any ATLAS→El Jefe feature
2. Should the Mac's Ollama serve the fleet? It is the strongest inference box
   (M1 Max, 32 GB unified) and is currently unreachable to everyone else
3. Auth posture: ATLAS uses a token; LENS and El Jefe have none

---

## 9. Standing constraints (from Steven, non-negotiable)

- **Never delete anything on `/Volumes/8TB`.**
- **Eastern Time, timezone-aware everywhere.** Never `utcnow()`, never naive
  datetimes. This has been a recurring bug across projects.
- **LENS is single-user, Steven only, forever.** Never add auth/portals/tenancy
  to LENS. (The multi-user product is Kitchen Window, separate.)
- **Local inference only** — Ollama, no cloud models.
- **Human approval gates all live posting.**
- Instagram captions: exactly **5 hashtags**.
- **No em-dashes in published prose** written under his name.
