"""MÁV ELVIRA timetable data for the BKK Stop integration."""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta

import zoneinfo

_LOGGER = logging.getLogger(__name__)

ELVIRA_URL = "https://jegy-a.mav.hu/IK_API_PROD/api/InformationApi/GetTimetable"
ELVIRA_CACHE_TTL = 45
ELVIRA_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json, text/plain, */*",
    "language": "hu",
    "Origin": "https://jegy.mav.hu",
    "Referer": "https://jegy.mav.hu/",
}
DOMAIN = "bkk_stop"

ARRIVAL_GRACE = timedelta(minutes=2)
STATIONINFO_MAX_COUNT = "500"
ELVIRA_ROW_CAP = 500


def station_code_digits(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) >= 9:
        return digits[-9:]
    return digits


def _iso_dt(value, tz):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _fold_hu(text: str) -> str:
    norm = unicodedata.normalize("NFKD", str(text or ""))
    return norm.encode("ascii", "ignore").decode("ascii").lower()


_BOOKING_REQUIRED_RE = re.compile(
    r"(?:SZOLGALTATAS[#:]|#|\b)3880\b",
    re.IGNORECASE,
)


def parse_elvira_services(row: dict) -> dict:
    flags = {"booking": False, "bikesAllowed": False, "wheelchair": False}
    for svc in row.get("services") or []:
        svc = svc or {}
        blob = " ".join(
            str(svc.get(key) or "")
            for key in ("description", "name", "shortName", "code", "key", "id")
        )
        low = _fold_hu(blob)
        required = _BOOKING_REQUIRED_RE.search(blob) or (
            "helyjegy" in low and "kotelezo" in low
        )
        if required:
            flags["booking"] = True
        if "kerekpar" in low:
            flags["bikesAllowed"] = True
        if "kerekesszek" in low:
            flags["wheelchair"] = True
    return flags


def track_from_elvira_row(row: dict) -> str:
    for key in ("startTrack", "endTrack"):
        raw = row.get(key)
        if raw is None or raw == "":
            continue
        text = str(raw).strip()
        if text and text.lower() != "none":
            return text
    return ""


def _label_from_row(row: dict) -> str:
    jel = ((row.get("viszonylatiJel") or {}).get("jel") or "").strip()
    if jel:
        return jel
    name = str(row.get("name") or row.get("fullShortType") or "").strip()
    if name:
        return name
    return str(row.get("code") or "IC")


async def _fetch_station(session, station_code: str, tz) -> tuple[list, list]:
    now = datetime.now(tz)
    travel = now.replace(hour=0, minute=0, second=0, microsecond=0)
    payload = {
        "type": "StationInfo",
        "travelDate": travel.strftime("%Y-%m-%dT%H:%M:%S"),
        "stationNumberCode": station_code,
        "minCount": "0",
        "maxCount": STATIONINFO_MAX_COUNT,
    }
    try:
        async with session.post(
            ELVIRA_URL,
            json=payload,
            headers=ELVIRA_HEADERS,
            timeout=30,
        ) as resp:
            if resp.status // 100 != 2:
                _LOGGER.warning(
                    "ELVIRA StationInfo %s HTTP %s", station_code, resp.status
                )
                return [], []
            data = await resp.json(content_type=None)
    except Exception as err:
        _LOGGER.warning("ELVIRA StationInfo %s failed: %s", station_code, err)
        return [], []
    details = (data or {}).get("stationSchedulerDetails") or {}
    return (
        list(details.get("departureScheduler") or []),
        list(details.get("arrivalScheduler") or []),
    )


async def _station_legs(session, hass, station_code: str):
    cache = hass.data.setdefault(DOMAIN, {}).setdefault("elvira_cache", {})
    cached = cache.get(station_code)
    now = time.time()
    tz = zoneinfo.ZoneInfo(hass.config.time_zone or "Europe/Budapest")
    day = datetime.now(tz).strftime("%Y-%m-%d")
    if (
        cached
        and cached.get("day") == day
        and now - cached.get("ts", 0) < ELVIRA_CACHE_TTL
    ):
        return cached.get("dep") or [], cached.get("arr") or []
    dep, arr = await _fetch_station(session, station_code, tz)
    cache[station_code] = {"ts": now, "day": day, "dep": dep, "arr": arr}
    return dep, arr


def rows_from_stationinfo(odep, darr, tz, now, latest, dest_name=""):
    """Build origin departures and optional destination arrival matches."""
    dest_by_id = {}
    dest_by_code = {}
    for row in darr or []:
        tid = str(row.get("trainId") or "")
        code = str(row.get("code") or "").strip()
        if tid:
            dest_by_id.setdefault(tid, row)
        if code:
            dest_by_code.setdefault(code, row)
    out = []
    for row in odep or []:
        start = _iso_dt(row.get("actualOrEstimatedStart") or row.get("start"), tz)
        if start is None:
            continue
        tid = str(row.get("trainId") or "")
        code = str(row.get("code") or "").strip()
        hit = dest_by_id.get(tid) or dest_by_code.get(code)
        arr = None
        if hit:
            arr = _iso_dt(
                hit.get("actualOrEstimatedArrive") or hit.get("arrive") or hit.get("start"),
                tz,
            )
        if arr is not None and (arr < now - ARRIVAL_GRACE or arr < start):
            hit = None
            arr = None
        if arr is None and start < now - ARRIVAL_GRACE:
            continue
        if start > latest and (arr is None or arr > latest):
            continue
        travel = None
        if arr is not None:
            travel = int((arr - start).total_seconds() / 60)
            if travel < 1 or travel > 1440:
                travel = None
        flags = parse_elvira_services(row)
        sched = _iso_dt(row.get("start"), tz) or start
        delay = int((start - sched).total_seconds()) if sched is not None else 0
        out.append({
            "tripId": "elvira:" + (tid or code),
            "label": _label_from_row(row),
            "head": dest_name or ((row.get("endStation") or {}).get("name") or ""),
            "dep": int(start.timestamp()),
            "sched": int(sched.timestamp()),
            "platform": track_from_elvira_row(row),
            "vehicle": "rail",
            "rawType": "RAIL",
            "trainNumber": code,
            "travel": travel,
            "destHit": bool(hit),
            "booking": bool(flags.get("booking")),
            "bikesAllowed": bool(flags.get("bikesAllowed")),
            "wheelchair": bool(flags.get("wheelchair")),
            "color": "#4477aa",
            "text": "#ffffff",
            "delay": delay,
        })
    out.sort(key=lambda item: item.get("dep") or 0)
    return out[:ELVIRA_ROW_CAP]


async def elvira_between(
    session, hass, origin_code, dest_code, minutes_after=180, dest_name=""
):
    origin_code = station_code_digits(origin_code)
    dest_code = station_code_digits(dest_code)
    if len(origin_code) < 9 or len(dest_code) < 9 or origin_code == dest_code:
        return []
    try:
        tz = zoneinfo.ZoneInfo(hass.config.time_zone or "Europe/Budapest")
    except Exception:
        tz = zoneinfo.ZoneInfo("Europe/Budapest")
    odep, _oarr = await _station_legs(session, hass, origin_code)
    try:
        _ddep, darr = await _station_legs(session, hass, dest_code)
    except Exception as err:
        _LOGGER.warning("ELVIRA dest StationInfo %s skipped: %s", dest_code, err)
        darr = []
    now = datetime.now(tz)
    latest = now + timedelta(minutes=int(minutes_after or 180))
    return rows_from_stationinfo(odep, darr, tz, now, latest, dest_name)
