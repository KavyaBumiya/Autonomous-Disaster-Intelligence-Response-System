"""Phase 18 — End-to-end production smoke (§48).

Flow: login → report ingest → cluster/incident → weather + GIS enrichment →
      evidence/XAI → prediction → real-OSRM route → priority → approval →
      WebSocket toast → health shape.

Runs against the local stack (http://localhost:8000) inside aegisai_backend.
Set E2E_BASE_URL to target another deployment (e.g. the Render URL).

Live external providers are hit for real (Open-Meteo, OSRM, USGS, Nominatim).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid

import httpx

# allow `python tests/e2e_smoke.py` (script dir is not the package root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000").rstrip("/")
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)


async def main() -> int:
    t0 = time.time()
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as c:

        # 0. health (new Phase-16 shape)
        h = (await c.get("/api/health")).json()
        check("health.status", h.get("status") in ("ok", "degraded"), h.get("status"))
        check("health.services.db", "database" in (h.get("services") or {}))
        check("health.providers.canonical", "weather" in (h.get("providers") or {}),
              str(list((h.get("providers") or {}).keys())))

        # 1. public demo mode — no bearer token required
        H: dict[str, str] = {}
        zone_id = "zone-alkapuri"

        # 1b. websocket client (connected first so it observes the whole run)
        ws_events: list[dict] = []
        try:
            import socketio
            sio = socketio.Client()

            @sio.event
            def connect():
                sio.emit("subscribe", {"room": "global_feed"})

            def _mk(name):
                def _handler(data):
                    ws_events.append({"name": name, "data": data})
                return _handler

            for ev in ("new_report", "incident_priority_updated", "action_state_changed",
                       "new_incident", "connected", "subscribed"):
                sio.on(ev, _mk(ev))
            sio.connect(BASE, wait_timeout=10)  # polling transport (websocket-client not installed)
            check("websocket.connect", sio.connected)
        except Exception as exc:
            check("websocket.connect", False, str(exc))
            sio = None

        # 2. report ingest (text flood report inside Alkapuri zone)
        marker = uuid.uuid4().hex[:8]
        body = {
            "message_text": f"[E2E {marker}] Severe flooding on the Alkapuri main road. "
                            "Water waist-deep near the flyover, families stranded, "
                            "need rescue boats immediately.",
            "lat": 22.3095, "lng": 73.189,
            "location_string": "Alkapuri Circle, Vadodara",
            "device_type": "web",
        }
        r = await c.post("/api/reports", json=body, headers=H)
        check("report.ingest", r.status_code == 201, f"HTTP {r.status_code}")
        report_id = r.json().get("id") if r.status_code == 201 else None

        # 3. wait for pipeline → incident clustering
        incident_id = None
        for _ in range(24):  # up to 48s (background: NLP → verification → decision)
            await asyncio.sleep(2)
            rr = await c.get("/api/incidents", headers=H,
                             params={"limit": 50, "active": "true"})
            if rr.status_code != 200:
                continue
            items = rr.json().get("incidents", [])
            hit = next((i for i in items if i.get("disaster_type") == "flood"
                        and (i.get("zone_id") or "").startswith(("zone-alkapuri", "97a6579a"))),
                       None)
            if hit:
                incident_id = hit.get("incident_id") or hit.get("id")
                check("incident.clustered", True,
                      f"{str(incident_id)[:8]} priority={hit.get('priority_score')}")
                break
        if incident_id is None:
            # fallback: any flood incident
            rr = await c.get("/api/incidents", headers=H, params={"limit": 10})
            items = rr.json().get("incidents", []) if rr.status_code == 200 else []
            hit = next((i for i in items if i.get("disaster_type") == "flood"), None)
            incident_id = (hit.get("incident_id") or hit.get("id")) if hit else None
            check("incident.clustered", incident_id is not None,
                  "fallback (zone match not found)" if incident_id else "no flood incident")

        # 4. weather enrichment (live Open-Meteo)
        r = await c.get("/api/weather/current", params={"lat": 22.3095, "lng": 73.189},
                        headers=H)
        w = r.json() if r.status_code == 200 else {}
        check("weather.current", r.status_code == 200 and w.get("provider") == "open-meteo",
              f"rain={w.get('rainfall_mm_hr')} cache={w.get('from_cache')}")

        # 4b. earthquakes (live USGS via 2-min poller → seismic_events)
        r = await c.get("/api/earthquakes/recent", headers=H,
                        params={"minutes": 1440, "min_magnitude": 2.0, "limit": 3})
        eq = r.json() if r.status_code == 200 else {}
        check("earthquakes.recent",
              r.status_code == 200 and eq.get("source") == "seismic_events",
              f"count={eq.get('count')}")

        # 4c. GIS/zone enrichment overview
        r = await c.get("/api/command/zone-status", headers=H,
                        params={"zone_id": zone_id})
        zs = r.json() if r.status_code == 200 else None
        check("gis.zone_status", r.status_code == 200 and zs.get("zone_name"),
              f"HTTP {r.status_code} zone={zs.get('zone_name') if isinstance(zs, dict) else None}")

        # 5. evidence / XAI attribution
        if incident_id:
            r = await c.get(f"/api/command/explain/{incident_id}", headers=H)
            ex = r.json() if r.status_code == 200 else {}
            keys = set(ex.keys()) if isinstance(ex, dict) else set()
            check("evidence.explain", r.status_code == 200 and bool(keys),
                  f"keys={sorted(keys)[:6]}")
        else:
            check("evidence.explain", False, "no incident")

        # 6. prediction (zone flood model, real inputs)
        r = await c.post("/api/predictions/flood", headers=H,
                         json={"zone_id": zone_id, "hours": 6})
        check("prediction.flood", r.status_code == 200, f"HTTP {r.status_code}")

        # 7. route computation — REAL OSRM (response: top-level source/penalties)
        r = await c.post("/api/routes/compute", headers=H,
                         json={"zone_id": zone_id, "disaster_type": "flood",
                               "origin_lat": 22.3095, "origin_lng": 73.189})
        rt = r.json() if r.status_code == 200 else {}
        prim = rt.get("primary_route") or {}
        check("route.osrm", r.status_code == 200 and rt.get("source") == "osrm",
              f"source={rt.get('source')} engine={rt.get('engine')} "
              f"dist={prim.get('distance_km')}km")
        check("route.contract",
              r.status_code == 200 and all(k in rt for k in
                                           ("zone_id", "primary_route", "alternate_routes",
                                            "source", "geometry", "cost", "penalties")),
              f"penalties={list((rt.get('penalties') or {}).keys()) or 'MISSING'} "
              f"geom_pts={len(rt.get('geometry') or [])}")

        # 8. priority heatmap
        r = await c.get("/api/heatmaps/priority", headers=H)
        hp = r.json() if r.status_code == 200 else None
        check("priority.heatmap", r.status_code == 200 and hp is not None, f"HTTP {r.status_code}")

        # 8b. NASA EONET natural events (poller ingest → domain read)
        try:
            from app.pollers.eonet import poll_eonet

            await poll_eonet()  # ensure fresh ingestion for this smoke run
            eonet_ok = True
        except Exception as exc:
            eonet_ok = False
            check("nasa.eonet_ingest", False, f"{type(exc).__name__}: {exc}")
        if eonet_ok:
            r = await c.get("/api/nasa/eonet/events", headers=H,
                            params={"limit": 10})
            ne = r.json() if r.status_code == 200 else {}
            evs = ne.get("events") or []
            check("nasa.eonet_events",
                  r.status_code == 200 and ne.get("source") == "nasa_eonet" and evs,
                  f"count={ne.get('count')} first={evs[0]['title'][:40] if evs else None}")

        # 9. approval gate — seed a severe scenario (values a production
        #    poller + Detection/CV agents would write), re-run the actual
        #    Decision Engine, then commander approves through the API.
        new_priority = None
        if incident_id:
            try:
                from datetime import datetime as _dt, timezone as _tz
                import uuid as _uuid

                from app.core.database import AsyncSessionLocal
                from app.engine.decision import score_zone
                from app.models.incident import Incident as _Inc
                from app.models.weather import WeatherReading

                async with AsyncSessionLocal() as db:
                    inc = await db.get(_Inc, incident_id)
                    if inc is None:
                        raise RuntimeError("incident row not found")
                    # poller-during-storm reading (§28 weather poller shape)
                    db.add(WeatherReading(
                        id=str(_uuid.uuid4()), zone_id=inc.zone_id,
                        lat=22.3095, lng=73.189,
                        rainfall_mm_hr=48.0, wind_speed_kmh=55.0, temperature_c=28.0,
                        weather_main="Rain", weather_description="Heavy rain",
                        risk_score=0.95, polled_at=_dt.now(_tz.utc),
                    ))
                    inc.victim_count = 60      # CV agent output (victim_detection)
                    inc.severity_score = 95.0  # Detection Agent severity
                    inc.created_at = _dt.now(_tz.utc)  # incident occurring now (fresh)
                    await db.flush()
                    decision = await score_zone(inc.zone_id, inc, db)
                    new_priority = decision["priority_score"]
                    await db.commit()
                check("approval.score_zone", new_priority is not None and new_priority >= 70,
                      f"priority={new_priority} (threshold=70)")
            except Exception as exc:
                check("approval.score_zone", False, f"{type(exc).__name__}: {exc}")
        else:
            check("approval.score_zone", False, "no incident to score")

        action_id = None
        for _ in range(6):
            r = await c.get("/api/command/approval-queue", headers=H)
            q = r.json() if r.status_code == 200 else {}
            items = q.get("actions") if isinstance(q, dict) else (q or [])
            pending = [a for a in (items or []) if a.get("status") == "pending_approval"]
            if pending:
                action_id = pending[0].get("action_id") or pending[0].get("id")
                break
            await asyncio.sleep(2)
        check("approval.queue", action_id is not None, f"action={action_id}")
        if action_id:
            r = await c.patch(f"/api/actions/{action_id}", headers=H,
                              json={"status": "approved", "note": "E2E smoke approval"})
            check("approval.approve", r.status_code == 200,
                  f"HTTP {r.status_code} {(r.json() or {}).get('message', '')}")

        # 10. WebSocket toast — did we receive live events during the run?
        await asyncio.sleep(3)
        names = sorted({e["name"] for e in ws_events})
        check("websocket.events", len(ws_events) > 0, f"received={names} total={len(ws_events)}")
        if sio and sio.connected:
            sio.disconnect()

    return finish(t0)


def finish(t0: float) -> int:
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{'=' * 60}")
    print(f"E2E SMOKE: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed "
          f"in {time.time() - t0:.1f}s")
    for name, _, detail in failed:
        print(f"  FAILED: {name} [{detail}]")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
