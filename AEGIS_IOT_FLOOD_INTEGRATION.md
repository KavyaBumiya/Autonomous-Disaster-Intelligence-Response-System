# Flood Sensor — Connecting a Device to AEGIS

A guide for the IoT team. Everything you need to get a flood sensor sending data
into the AEGIS dashboard.

---

## The 30-second version

Your device does one thing: **POST a water level and flow velocity to AEGIS every
few seconds.** AEGIS stores it, works out the flood risk, and shows it on the
dashboard live.

That's it. Three steps:

| Step | What you do |
|---|---|
| **1** | Ask the backend for a device token (one time) |
| **2** | Store that token in your device |
| **3** | POST readings, every 5–30 seconds |

Full walkthrough below.

---

## Step 1 — Get a device token

This is done **once**, by whoever sets up the system. Not by the device itself.

```bash
curl -X POST "http://localhost:8000/api/iot/v1/devices/register" \
  -H "Authorization: Bearer dev-registration-token-local" \
  -H "Content-Type: application/json" \
  -d '{"device_id":"FLOOD-001","name":"Sabarmati Gauge","lat":22.3072,"lng":73.1812}'
```

You get back:

```json
{
  "device_id": "FLOOD-001",
  "token": "dc656ef2cfb1a4e8f... 48 characters ...",
  "status": "active"
}
```

> **Save that token now. It is shown exactly once and cannot be retrieved again.**
> AEGIS only keeps a hash of it. If you lose it, register a new device id.

The token goes in your device's firmware. It is a device secret — don't put it
in any web page or share it.

---

## Step 2 — Send a reading

Every 5–30 seconds, from the device:

```bash
curl -X POST "http://localhost:8000/api/iot/v1/telemetry" \
  -H "Authorization: Bearer YOUR_DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "FLOOD-001",
    "water_level": 1.18,
    "flow_velocity": 0.64,
    "timestamp": "2026-09-29T16:30:00Z",
    "event_id": "reading-00042"
  }'
```

Success:

```json
{ "id": "0f1e...", "status": "accepted", "risk_level": "NORMAL", "risk_score": 0.0 }
```

**Done.** That reading is now on the dashboard.

---

## Step 3 — Don't send duplicates

Sensors retry when the network is flaky. If a retry arrives twice you'd get the
same reading counted twice.

That's what `event_id` is for. Give every reading a unique id:

```
"event_id": "reading-00042"     ← sending this again
```

AEGIS recognises the repeat and returns `"status": "duplicate"` without storing a
second copy. **Always send one.** A good value is boot-count + counter:

```python
event_id = f"boot-{boot_count}-{sequence}"
```

---

## The two secrets

There are two different tokens. They are not interchangeable.

| | Bootstrap token | Device token |
|---|---|---|
| **Used for** | Registering a *new* device | Sending and reading data |
| **Who has it** | System administrator | Each individual device |
| **Who sends it** | Human, during setup | The device, on every request |
| **Changes** | Never | One per device |
| **Send it in the browser?** | No | **No** — that's why the dashboard doesn't need one |

In code they look the same:

```
Authorization: Bearer <token>
```

The server just knows which one you sent and checks it against the right list.

---

## What the numbers mean

**Units matter. Please double-check these.**

| Field | Unit | Range | Example |
|---|---|---|---|
| `water_level` | **metres** | 0 – 50 | `1.18` means 1.18 m |
| `flow_velocity` | **metres per second** | 0 – 100 | `0.64` means 0.64 m/s |
| `lat` / `lng` | **degrees** (WGS84) | lat ±90, lng ±180 | `22.3072`, `73.1812` |
| `timestamp` | ISO 8601 with timezone | — | `2026-09-29T16:30:00Z` |

> If your sensor reports centimetres, convert before sending: `metres = cm / 100`.
> A centimetre reading sent as metres would look like a catastrophic flood.

---

## Full field reference

| Field | Required | Type | Notes |
|---|---|---|---|
| `device_id` | **yes** | string | Must match your token. Letters, digits, `-`, `_` only |
| `water_level` | **yes** | number | Metres, 0–50 |
| `flow_velocity` | **yes** | number | m/s, 0–100 |
| `timestamp` | **yes** | string | Your device's clock. Include `Z` or an offset |
| `event_id` | no | string | Up to 80 chars. **Strongly recommended** |
| `lat` | no | number | Degrees, −90 to 90 |
| `lng` | no | number | Degrees, −180 to 180 |
| `source` | no | string | `"iot"` (default) or `"simulation"` |

---

## Reading data back

These are dashboard reads — **no token needed.** The console uses them.

```
GET /api/iot/v1/devices                          # list enrolled devices
GET /api/iot/v1/devices/{device_id}/latest       # current reading
GET /api/iot/v1/devices/{device_id}/history      # past readings
```

### Latest

```json
{
  "device_id": "FLOOD-001",
  "water_level": 1.18,
  "flow_velocity": 0.64,
  "timestamp": "2026-09-29T16:30:00+00:00",
  "received_at": "2026-09-29T16:30:02.113+00:00",
  "age_seconds": 4.2,
  "risk_level": "NORMAL",
  "risk_score": 0.0,
  "device_status": "active",
  "battery_pct": 92
}
```

> **Two different times, on purpose.**
> `timestamp` is when **your device** measured it.
> `received_at` is when **AEGIS** got it.
> On a slow network these differ by seconds or minutes. The dashboard shows the
> device time, because that's when the water was actually there.

`404` means the device has never sent anything.

### History

```
GET /api/iot/v1/devices/FLOOD-001/history?limit=100
GET /api/iot/v1/devices/FLOOD-001/history?from=2026-09-29T00:00:00Z&to=2026-09-29T23:59:59Z
```

Oldest first, ready to plot straight onto a chart. `limit` is 1–1000, default 100.

```json
[
  { "water_level": 1.10, "flow_velocity": 0.50, "timestamp": "...", "risk_level": "NORMAL" },
  { "water_level": 1.80, "flow_velocity": 0.90, "timestamp": "...", "risk_level": "WARNING" }
]
```

---

## Live updates on the dashboard

The dashboard updates without refreshing. To listen yourself:

```js
const sio = io("https://autonomous-disaster-intelligence.onrender.com");

// Subscribe first — without this you get nothing
sio.emit("subscribe", { room: "global_feed" });

sio.on("flood.sensor.updated", (msg) => {
  console.log(msg.payload.water_level, msg.payload.risk_level);
});
```

You get this whenever a reading is accepted:

```json
{ "event": "flood.sensor.updated",
  "payload": { "device_id": "FLOOD-001",
               "water_level": 1.18, "flow_velocity": 0.64,
               "risk_level": "NORMAL", "risk_score": 0.0, "source": "iot" },
  "timestamp": "2026-09-29T16:30:02.198Z" }
```

> The `subscribe` message **must** contain an object: `{"room": "global_feed"}`.
> Sending the bare string `"global_feed"` fails silently and you get no events.

---

## How flood risk is worked out

Straightforward thresholds — no machine learning, nothing to tune:

| Band | water_level (m) | flow_velocity (m/s) |
|---|---|---|
| LOW | under 1.5 | under 1.0 |
| MEDIUM | 1.5 and up | 1.0 and up |
| HIGH | 2.5 and up | 2.0 and up |
| CRITICAL | 3.5 and up | 3.0 and up |

The overall risk is whichever band is worse. `risk_score` is just that severity
as a number: `0.0`, `0.333`, `0.667`, or `1.0`.

**These are the exact same numbers the dashboard's simulation mode uses**, so
Live and Sim always agree on what "warning" means.

---

## Simulation mode still works

Unchanged, and unrelated to your device. It's the **Sim** button on the flood
page — fully in the browser, no backend needed.

The **Live** button shows your real sensor data. That's this integration.

Both modes read and display identically.

---

## When something goes wrong

| Code | What it means | What to do |
|---|---|---|
| `401` | No token sent | Check your `Authorization` header |
| `403` | Wrong device | Token doesn't match that `device_id` |
| `404` | No data yet | Device registered but never reported |
| `409` | Already registered | Use a different `device_id` |
| `422` | Bad value | Check units and ranges — see the table above |
| `429` | Too fast | Slow down; see retry below |
| `500` | Server problem | Retry shortly |

**Most common causes:** centimetres sent as metres, no `Authorization` header,
or a timestamp with no timezone.

---

## Retrying safely

| Response | Retry? |
|---|---|
| Network error / timeout | Yes, back off |
| `500`, `502`, `503` | Yes, back off |
| `429` | Yes — but slower, and respect `Retry-After` |
| `400`, `401`, `403`, `409`, `422` | **No** — the same data will fail again |

Back off: 1s → 2s → 4s, cap at 10s, with a bit of random jitter. Because of
`event_id`, retrying is always safe.

---

## Ready-to-run examples

### Python

```python
import time, httpx

BASE = "https://autonomous-disaster-intelligence.onrender.com"
DEVICE_TOKEN = "your-token-here"
seq = 0

while True:
    seq += 1
    httpx.post(
        f"{BASE}/api/iot/v1/telemetry",
        headers={"Authorization": f"Bearer {DEVICE_TOKEN}"},
        json={
            "device_id": "FLOOD-001",
            "water_level": 1.18,
            "flow_velocity": 0.64,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event_id": f"reading-{seq:05d}",
        },
        timeout=15,
    )
    time.sleep(10)
```

### ESP32 / microPython

```python
import urequests as requests, time, json

while True:
    body = json.dumps({
        "device_id": "FLOOD-001",
        "water_level": 1.18,
        "flow_velocity": 0.64,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_id": str(int(time.time())),
    })
    requests.post(
        "https://autonomous-disaster-intelligence.onrender.com/api/iot/v1/telemetry",
        data=body,
        headers={"Authorization": "Bearer " + DEVICE_TOKEN,
                 "Content-Type": "application/json"},
    )
    time.sleep(10)
```

---

## Interactive docs

Browse and try every endpoint directly:

**https://autonomous-disaster-intelligence.onrender.com/docs**

Look for the section tagged **iot**.

---

## Where your data lives

| Table | Holds |
|---|---|
| `flood_devices` | Your device: id, name, location, token hash, battery, last seen |
| `flood_telemetry` | Every reading: both values, device time, server time, risk result |

Indexed on `(device_id, timestamp)` so history queries stay fast.

---

## Checklist before you hand off

- [ ] Sensor reports **metres**, not centimetres
- [ ] Flow velocity in **m/s**
- [ ] `timestamp` includes a timezone (`Z` or `+05:30`)
- [ ] Every reading has a unique `event_id`
- [ ] `Authorization: Bearer <your token>` on every POST
- [ ] `device_id` in the body matches the one you registered
- [ ] You can see the reading on the dashboard in **Live** mode

---

## Questions?

- **How do I get a device token?** → Step 1. Ask the backend admin for the
  bootstrap token.
- **How often should I send?** → Every 5–30 seconds. The rate limit is 12/minute.
- **What if the network drops?** → Retry with backoff. `event_id` makes it safe.
- **Can I send more than water level?** → Yes — add `lat`/`lng`/`battery_pct` to
  the body; the fields are already supported.
