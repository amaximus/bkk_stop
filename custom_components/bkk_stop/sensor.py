import asyncio
import logging
import re
import time
import zoneinfo
from datetime import datetime, timedelta

import aiohttp
import voluptuous as vol

from homeassistant.components.sensor import ENTITY_ID_FORMAT, PLATFORM_SCHEMA
from homeassistant.const import ATTR_ENTITY_ID, CONF_NAME
from homeassistant.core import ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity, async_generate_entity_id

REQUIREMENTS = []

_LOGGER = logging.getLogger(__name__)

CONF_APIKEY = "apiKey"
CONF_BIKES = "bikes"
CONF_COLORS = "colors"
CONF_HEADSIGNS = "headsigns"
CONF_IGNORENOW = "ignoreNow"
CONF_INPREDICTED = "inPredicted"
CONF_MINSAFTER = "minsAfter"
CONF_MAXITEMS = "maxItems"
CONF_ROUTES = "routes"
CONF_STOPID = "stopId"
CONF_MINSBEFORE = "minsBefore"
CONF_WHEELCHAIR = "wheelchair"
CONF_VEHICLE = "vehicle"
CONF_FAILURE_THRESHOLD = "failureThreshold"
CONF_ELVIRA = "elvira"

DEFAULT_NAME = "Budapest GO"
DEFAULT_ICON = "mdi:bus"
DEFAULT_FAILURE_THRESHOLD = 3
DOMAIN = "bkk_stop"
SENSOR_PLATFORM = "sensor"
EVENT_API_FAILED = "bkk_stop_api_failed"
EVENT_API_RECOVERED = "bkk_stop_api_recovered"

# Unofficial MÁV ELVIRA passenger-info API (jegy.mav.hu). Used for live track/platform.
ELVIRA_API_BASE = "https://jegy-a.mav.hu/IK_API_PROD/api"
ELVIRA_TIMETABLE_PATH = "/InformationApi/GetTimetable"
ELVIRA_CACHE_TTL = 45  # seconds; shared across sensors for the same station
# BKK rail stop IDs often reuse the 9-digit MÁV station code: BKK_005501024
_ELVIRA_STOP_RE = re.compile(r"^BKK_(\d{9})$")

SHAPE_CACHE_TTL = 6 * 3600  # trip geometry changes rarely
SHAPE_MAX_POINTS = 220  # keep HA attributes compact
SHAPE_FETCH_LIMIT = 12  # max trip-details calls per sensor update
BKK_TRIP_DETAILS = (
    "https://go.bkk.hu/api/query/v1/ws/otp/api/where/trip-details.json"
)

REFRESH_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): vol.All(cv.ensure_list, [cv.string]),
    }
)

HTTP_TIMEOUT = 60  # secs
MAX_RETRIES = 3
SCAN_INTERVAL = timedelta(seconds=30)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(ATTR_ENTITY_ID, default=""): cv.string,
        vol.Required(CONF_APIKEY): cv.string,
        vol.Required(CONF_STOPID): cv.string,
        vol.Optional(CONF_BIKES, default=False): cv.boolean,
        vol.Optional(CONF_COLORS, default=False): cv.boolean,
        vol.Optional(CONF_HEADSIGNS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_IGNORENOW, default="true"): cv.boolean,
        vol.Optional(CONF_INPREDICTED, default="false"): cv.boolean,
        vol.Optional(CONF_MAXITEMS, default=0): cv.string,
        vol.Optional(CONF_MINSAFTER, default=20): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_ROUTES, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_MINSBEFORE, default=0): cv.string,
        vol.Optional(CONF_WHEELCHAIR, default=False): cv.boolean,
        vol.Optional(CONF_VEHICLE, default=True): cv.boolean,
        vol.Optional(CONF_ELVIRA, default=True): cv.boolean,
        vol.Optional(CONF_FAILURE_THRESHOLD, default=DEFAULT_FAILURE_THRESHOLD): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=20)
        ),
    }
)


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    name = config.get(CONF_NAME)
    entityid = config.get(ATTR_ENTITY_ID)

    stopid = config.get(CONF_STOPID)
    maxitems = config.get(CONF_MAXITEMS)
    minsafter = config.get(CONF_MINSAFTER)
    wheelchair = config.get(CONF_WHEELCHAIR)
    bikes = config.get(CONF_BIKES)
    colors = config.get(CONF_COLORS)
    ignorenow = config.get(CONF_IGNORENOW)
    routes = config.get(CONF_ROUTES)
    headsigns = config.get(CONF_HEADSIGNS)
    inpredicted = config.get(CONF_INPREDICTED)
    minsbefore = config.get(CONF_MINSBEFORE)
    apikey = config.get(CONF_APIKEY)
    vehicle = config.get(CONF_VEHICLE)
    elvira = config.get(CONF_ELVIRA)
    failure_threshold = config.get(CONF_FAILURE_THRESHOLD)

    async_add_devices(
        [
            BKKPublicTransportSensor(
                hass,
                name,
                entityid,
                stopid,
                minsafter,
                wheelchair,
                bikes,
                colors,
                ignorenow,
                maxitems,
                routes,
                inpredicted,
                apikey,
                headsigns,
                minsbefore,
                vehicle,
                failure_threshold,
                elvira,
            )
        ],
        update_before_add=True,
    )


def _sleep(secs):
    time.sleep(secs)


def _translated(value, lang="hu"):
    """Extract human text from BKK bilingual alert fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        translations = value.get("translations") or {}
        if lang in translations:
            return translations[lang]
        if "en" in translations:
            return translations["en"]
        if value.get("someTranslation"):
            return value["someTranslation"]
        if translations:
            return next(iter(translations.values()))
    return str(value)


def _elvira_station_code(stopid):
    """Derive MÁV station number code from a BKK stop id, if applicable."""
    if not stopid:
        return None
    match = _ELVIRA_STOP_RE.match(str(stopid).strip())
    return match.group(1) if match else None


def _norm_name(value):
    text = (value or "").strip().lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    # Common BKK vs MÁV naming differences
    for suffix in (" vasútállomás", " pályaudvar", " pu."):
        if text.endswith(suffix):
            text = text[: -len(suffix)].rstrip()
    return text


def _iso_hm(value):
    """Extract HH:MM from an ELVIRA ISO datetime string."""
    if not value or not isinstance(value, str) or len(value) < 16:
        return None
    # 2026-08-08T12:45:00+02:00
    return value[11:16]


def _route_matches_elvira(routeid, row):
    """Score how well a BKK route label matches an ELVIRA scheduler row."""
    route = (routeid or "").strip().upper()
    if not route:
        return 0
    jel = ((row.get("viszonylatiJel") or {}).get("jel") or "").strip().upper()
    if jel and jel == route:
        return 3
    full_short = (row.get("fullShortType") or "").strip().upper()
    full_type = (row.get("fullType") or "").strip().upper()
    if route in full_short.split() or route == full_short:
        return 2
    if route and route in full_type:
        return 1
    for kind in row.get("kinds") or []:
        name = (kind.get("name") or "").strip().upper()
        sort_name = (kind.get("sortName") or "").strip().upper()
        if route == sort_name or route in name.split() or name.startswith(route):
            return 2
        # e.g. "InterCity" vs IC, "InterRégió" vs IR
        aliases = {
            "IC": ("INTERCITY", "IC "),
            "EC": ("EUROCITY", "EC "),
            "EN": ("EURONIGHT",),
            "IR": ("INTERRÉGIÓ", "INTERREGIO", "IR "),
            "EX": ("EXPRESSZ", "EX "),
            "RJX": ("RAILJET",),
            "S": ("SZEMÉLY",),
            "SZ": ("SZEMÉLY",),
            "GY": ("GYORS",),
            "G": ("GYORSÍTOTT", "GYORS"),
        }
        for alias in aliases.get(route, ()):
            if alias in name:
                return 2
    return 0


def _match_elvira_row(attime, routeid, headsign, rows):
    """Pick the best ELVIRA departure/arrival row for a BKK vehicle."""
    if not attime or not rows:
        return None
    head = _norm_name(_strip_platform_suffix(headsign))
    best = None
    best_score = -1
    for row in rows:
        sched_hm = _iso_hm(row.get("start"))
        # Through trains at this station may only have arrive filled on ARR list;
        # for DEP list start is the local departure clock.
        if sched_hm != attime:
            continue
        score = 1  # time match
        score += _route_matches_elvira(routeid, row)
        dest = _norm_name((row.get("endStation") or {}).get("name"))
        origin = _norm_name((row.get("startStation") or {}).get("name"))
        if head:
            if head == dest or head == origin:
                score += 3
            elif head in dest or dest in head or head in origin or origin in head:
                score += 2
        if score > best_score:
            best_score = score
            best = row
    # Require at least time + (route or destination) to avoid wrong track
    if best is None or best_score < 3:
        return None
    return best


def _strip_platform_suffix(headsign):
    """Remove baked-in ' · vág.N' before matching / comparing headsigns."""
    text = headsign or ""
    return re.sub(r"\s*·\s*vág\.\S+\s*$", "", text, flags=re.I).strip()


def _parse_elvira_services(row):
    """Derive booking / dining / bike flags from ELVIRA service descriptions."""
    services = row.get("services") or []
    texts = []
    for svc in services:
        if not isinstance(svc, dict):
            continue
        desc = (svc.get("description") or "").strip()
        if desc:
            texts.append(desc)
    blob = " | ".join(texts).lower()
    flags = {}
    if "helyjegy váltása kötelező" in blob or (
        "helyjegy" in blob and "kötelező" in blob
    ):
        flags["booking"] = True
    if any(x in blob for x in ("étkezőkocsi", "étkező", "bisztró", "bistro")):
        flags["dining"] = True
    if "kerékpár nem szállítható" in blob:
        flags["bikesAllowed"] = False
    elif "kerékpár" in blob:
        flags["bikesAllowed"] = True
        if "foglalás" in blob and "kötelező" in blob:
            flags["bikeReservation"] = True
    return flags, texts


def _track_from_elvira_row(row):
    """Local platform/track at the queried station."""
    if not row:
        return None, None
    track = row.get("startTrack") or row.get("endTrack")
    track_type = row.get("startTrackType") or row.get("endTrackType")
    if track is None or str(track).strip() == "":
        return None, None
    return str(track).strip(), track_type


def _decode_polyline(encoded):
    """Decode a Google-encoded polyline into [[lat, lon], ...]."""
    if not encoded or not isinstance(encoded, str):
        return []
    coords = []
    index = 0
    lat = 0
    lng = 0
    length = len(encoded)
    try:
        while index < length:
            for is_lat in (True, False):
                result = 0
                shift = 0
                while True:
                    byte = ord(encoded[index]) - 63
                    index += 1
                    result |= (byte & 0x1F) << shift
                    shift += 5
                    if byte < 0x20:
                        break
                delta = ~(result >> 1) if result & 1 else (result >> 1)
                if is_lat:
                    lat += delta
                else:
                    lng += delta
            coords.append([lat / 1e5, lng / 1e5])
    except (IndexError, ValueError) as err:
        _LOGGER.debug("polyline decode failed: %s", err)
        return []
    return coords


def _downsample_coords(coords, max_points=SHAPE_MAX_POINTS):
    """Keep endpoints and evenly spaced samples for map drawing."""
    if not coords or len(coords) <= max_points:
        return coords
    if max_points < 2:
        return [coords[0], coords[-1]]
    step = (len(coords) - 1) / (max_points - 1)
    out = []
    for i in range(max_points):
        idx = int(round(i * step))
        if idx >= len(coords):
            idx = len(coords) - 1
        pt = coords[idx]
        if not out or out[-1] != pt:
            out.append(pt)
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out


async def _fetch_trip_shape(session, hass, apikey, trip_id):
    """Fetch and cache a downsampled trip shape from BKK trip-details."""
    cache = hass.data.setdefault(DOMAIN, {}).setdefault("shape_cache", {})
    now = time.time()
    cached = cache.get(trip_id)
    if cached and (now - cached.get("ts", 0)) < SHAPE_CACHE_TTL and cached.get("shape"):
        return cached["shape"]

    params = (
        f"key={apikey}&version=4&appVersion=apiary-1.0&tripId={trip_id}"
    )
    url = f"{BKK_TRIP_DETAILS}?{params}"
    try:
        async with session.get(url, timeout=HTTP_TIMEOUT) as response:
            if response.status // 100 != 2:
                _LOGGER.debug(
                    "trip-details HTTP %s for %s", response.status, trip_id
                )
                return (cached or {}).get("shape")
            data = await response.json(content_type=None)
    except Exception as err:
        _LOGGER.debug("trip-details failed for %s: %s", trip_id, err)
        return (cached or {}).get("shape")

    entry = ((data or {}).get("data") or {}).get("entry") or {}
    poly = entry.get("polyline") or {}
    encoded = poly.get("points") if isinstance(poly, dict) else None
    shape = _downsample_coords(_decode_polyline(encoded))
    if shape:
        cache[trip_id] = {"ts": now, "shape": shape}
    return shape or None


async def _fetch_elvira_departures(session, hass, station_code, mins_after=120):
    """Fetch ELVIRA station departures (cached briefly in hass.data).

    Returns (rows, station_havaria_infos).
    """
    cache = hass.data.setdefault(DOMAIN, {}).setdefault("elvira_cache", {})
    now = time.time()
    cached = cache.get(station_code)
    if cached and (now - cached.get("ts", 0)) < ELVIRA_CACHE_TTL:
        return cached.get("rows") or [], cached.get("havaria") or []

    # Look a bit behind so delayed trains still match on scheduled attime
    try:
        tz = zoneinfo.ZoneInfo(hass.config.time_zone or "Europe/Budapest")
    except Exception:
        tz = zoneinfo.ZoneInfo("Europe/Budapest")
    travel_dt = datetime.now(tz) - timedelta(minutes=10)
    payload = {
        "type": "StationInfo",
        "travelDate": travel_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "stationNumberCode": station_code,
        "minCount": "0",
        "maxCount": str(max(80, int(mins_after or 120) + 40)),
    }
    url = ELVIRA_API_BASE + ELVIRA_TIMETABLE_PATH
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, text/plain, */*",
        "language": "hu",
        "Origin": "https://jegy.mav.hu",
        "Referer": "https://jegy.mav.hu/",
    }
    try:
        async with session.post(
            url, json=payload, headers=headers, timeout=HTTP_TIMEOUT
        ) as response:
            if response.status // 100 != 2:
                _LOGGER.debug(
                    "ELVIRA timetable HTTP %s for station %s",
                    response.status,
                    station_code,
                )
                return (cached or {}).get("rows") or [], (cached or {}).get("havaria") or []
            data = await response.json(content_type=None)
    except Exception as err:
        _LOGGER.debug(
            "ELVIRA timetable fetch failed for %s: %s", station_code, err
        )
        return (cached or {}).get("rows") or [], (cached or {}).get("havaria") or []

    details = (data or {}).get("stationSchedulerDetails") or {}
    # Prefer departures; include arrivals so through-train track still matches
    rows = list(details.get("departureScheduler") or [])
    seen = {id(r) for r in rows}
    for row in details.get("arrivalScheduler") or []:
        if id(row) not in seen:
            rows.append(row)
            seen.add(id(row))
    havaria = [
        h for h in (details.get("havariaInfos") or []) if isinstance(h, str) and h.strip()
    ]
    cache[station_code] = {"ts": now, "rows": rows, "havaria": havaria}
    return rows, havaria


class BKKPublicTransportSensor(Entity):
    def __init__(
        self,
        hass,
        name,
        entityid,
        stopid,
        minsafter,
        wheelchair,
        bikes,
        colors,
        ignorenow,
        maxitems,
        routes,
        inpredicted,
        apikey,
        headsigns,
        minsbefore,
        vehicle,
        failure_threshold=DEFAULT_FAILURE_THRESHOLD,
        elvira=True,
    ):
        async def handle_refresh(call: ServiceCall) -> None:
            """Handle the refresh service call."""
            _LOGGER.debug("called refesh for %s", self._stopid)
            self.async_schedule_update_ha_state(force_refresh=True)

        self._name = name
        self._hass = hass
        self._stopid = stopid
        self._maxitems = maxitems
        self._minsafter = minsafter
        self._wheelchair = wheelchair
        self._bikes = bikes
        self._colors = colors
        self._ignorenow = ignorenow
        self._inpredicted = inpredicted
        self._apikey = apikey
        self._routes = routes
        self._headsigns = headsigns
        self._minsbefore = minsbefore
        self._vehicle = vehicle
        self._elvira = bool(elvira)
        self._elvira_station = _elvira_station_code(stopid) if self._elvira else None
        self._elvira_rows = []
        self._elvira_havaria = []
        self._elvira_ok = None
        self._shapes = {}
        self._failure_threshold = int(failure_threshold or DEFAULT_FAILURE_THRESHOLD)
        self._consecutive_failures = 0
        self._last_error = None
        self._state = None
        self._bkkdata = {}
        self._tz = zoneinfo.ZoneInfo(hass.config.time_zone)
        self._icon = DEFAULT_ICON
        if entityid == "":
            self.entity_id = async_generate_entity_id(
                ENTITY_ID_FORMAT, name, None, hass
            )
        else:
            self.entity_id = async_generate_entity_id(
                ENTITY_ID_FORMAT, entityid, None, hass
            )

        domain_data = hass.data.setdefault(DOMAIN, {})
        domain_data.setdefault(SENSOR_PLATFORM, {})
        domain_data.setdefault(
            "api_alert",
            {"active": False, "failing_entities": set()},
        )
        hass.services.async_register(
            DOMAIN,
            "refresh",
            handle_refresh,
            schema=REFRESH_SCHEMA,
        )

    def _health_attributes(self):
        """Attributes always exposed for API health monitoring."""
        attrs = {
            "consecutive_failures": self._consecutive_failures,
            "api_ok": self._consecutive_failures == 0,
            "failure_threshold": self._failure_threshold,
        }
        if self._last_error:
            attrs["last_error"] = self._last_error
        if self._elvira_station:
            attrs["elvira_station"] = self._elvira_station
            if self._elvira_ok is not None:
                attrs["elvira_ok"] = self._elvira_ok
        return attrs

    def _apply_elvira_track(self, stopdata):
        """Enrich RAIL rows from cached ELVIRA timetable (track, services, delay)."""
        if not self._elvira_rows or stopdata.get("type") != "RAIL":
            return
        row = _match_elvira_row(
            stopdata.get("attime"),
            stopdata.get("routeid"),
            stopdata.get("headsign"),
            self._elvira_rows,
        )
        if not row:
            return

        track, track_type = _track_from_elvira_row(row)
        if track:
            stopdata["platform"] = track
            if track_type:
                stopdata["platformType"] = track_type
            # Bake into headsign so it shows even if the Lovelace card JS is cached.
            head = _strip_platform_suffix(stopdata.get("headsign") or "")
            marker = f" · vág.{track}"
            stopdata["headsign"] = f"{head}{marker}"

        train_no = row.get("code")
        if train_no:
            stopdata["trainNumber"] = str(train_no)

        train_name = (row.get("name") or "").strip()
        if train_name:
            stopdata["trainName"] = train_name

        hav = row.get("havarianInfok") or {}
        reason = (hav.get("kesesiOk") or "").strip()
        info = (hav.get("kesesInfo") or "").strip()
        if reason:
            stopdata["delayReason"] = reason
        elif info:
            stopdata["delayReason"] = info
        if stopdata.get("delay") is None and hav.get("aktualisKeses") not in (None, ""):
            try:
                mins = int(hav.get("aktualisKeses") or 0)
                if mins:
                    stopdata["delay"] = mins * 60
            except (TypeError, ValueError):
                pass

        flags, service_texts = _parse_elvira_services(row)
        if flags.get("booking"):
            stopdata["booking"] = True
        if flags.get("dining"):
            stopdata["dining"] = True
        if "bikesAllowed" in flags:
            stopdata["bikesallowed"] = flags["bikesAllowed"]
            stopdata["bikesAllowed"] = flags["bikesAllowed"]
        if flags.get("bikeReservation"):
            stopdata["bikeReservation"] = True
        # Keep a short service tip list for the card (cap size)
        useful = [
            t
            for t in service_texts
            if any(
                k in t.lower()
                for k in (
                    "helyjegy",
                    "étkező",
                    "bisztró",
                    "kerékpár",
                    "1. osztály",
                    "prémium",
                    "business",
                    "klímás",
                )
            )
        ]
        if useful:
            stopdata["services"] = useful[:6]

    def _track_api_result(self, success, error=None):
        """Update consecutive-failure counters and fire HA events at threshold."""
        alert = self._hass.data[DOMAIN]["api_alert"]
        failing = alert["failing_entities"]

        if success:
            self._consecutive_failures = 0
            self._last_error = None
            failing.discard(self.entity_id)
            if alert["active"] and not failing:
                alert["active"] = False
                self._hass.bus.async_fire(
                    EVENT_API_RECOVERED,
                    {
                        "entity_id": self.entity_id,
                        "name": self._name,
                        "stop_id": self._stopid,
                    },
                )
                _LOGGER.info(
                    "BKK API recovered for %s (%s)", self.entity_id, self._stopid
                )
            return

        self._consecutive_failures += 1
        self._last_error = error or "unknown error"
        _LOGGER.warning(
            "BKK API failure #%s for %s (%s): %s",
            self._consecutive_failures,
            self.entity_id,
            self._stopid,
            self._last_error,
        )
        if self._consecutive_failures >= self._failure_threshold:
            failing.add(self.entity_id)
            if not alert["active"]:
                alert["active"] = True
                self._hass.bus.async_fire(
                    EVENT_API_FAILED,
                    {
                        "entity_id": self.entity_id,
                        "name": self._name,
                        "stop_id": self._stopid,
                        "consecutive_failures": self._consecutive_failures,
                        "failure_threshold": self._failure_threshold,
                        "error": self._last_error,
                        "failing_entities": sorted(failing),
                    },
                )
                _LOGGER.error(
                    "BKK API unhealthy after %s failures (threshold %s) for %s",
                    self._consecutive_failures,
                    self._failure_threshold,
                    self.entity_id,
                )

    @property
    def extra_state_attributes(self):
        bkkjson = self._health_attributes()
        bkkdata = self._bkkdata
        itemnr = 0

        if "status" not in bkkdata or bkkdata["status"] != "OK":
            return bkkjson

        refs = bkkdata["data"]["references"]
        entry = bkkdata["data"]["entry"]
        stop_ref = refs["stops"].get(self._stopid) or {}
        bkkjson["stationName"] = stop_ref.get("name", self._stopid)
        if stop_ref.get("direction") not in (None, ""):
            bkkjson["direction"] = stop_ref.get("direction")
        if "wheelchairBoarding" in stop_ref:
            bkkjson["wheelchairBoarding"] = stop_ref["wheelchairBoarding"]

        bkkjson["vehicles"] = []
        bkkjson["alerts"] = []
        if self._elvira_havaria:
            bkkjson["stationHavaria"] = list(self._elvira_havaria)

        alert_refs = refs.get("alerts") or {}
        seen_alerts = set()

        def add_alert(alert_id):
            if not alert_id or alert_id in seen_alerts or alert_id not in alert_refs:
                return
            seen_alerts.add(alert_id)
            alert = alert_refs[alert_id]
            bkkjson["alerts"].append(
                {
                    "id": alert_id,
                    "header": _translated(alert.get("header")),
                    "description": _translated(alert.get("description")),
                    "url": _translated(alert.get("url")),
                    "priority": alert.get("priority"),
                }
            )

        for alert_id in entry.get("alertIds") or []:
            add_alert(alert_id)

        if len(entry.get("stopTimes") or []) != 0:
            currenttime = int(bkkdata["currentTime"] / 1000)

            for stopTime in entry["stopTimes"]:
                attime = stopTime.get("departureTime")
                predicted_attime = stopTime.get("predictedDepartureTime")

                diff = int((attime or 0) - currenttime) / 60
                if self._inpredicted and predicted_attime:
                    diff = int((predicted_attime - currenttime) / 60)
                diff = int(diff)

                if diff < 0:
                    diff = 0
                if self._ignorenow and diff == 0 and not stopTime.get("canceled"):
                    continue

                tripid = stopTime.get("tripId")
                trip = refs["trips"].get(tripid) or {}
                routeid = trip.get("routeId")
                route = refs["routes"].get(routeid) or {}

                stopdata = {}
                stopdata["in"] = str(diff)
                stopdata["type"] = route.get("type", "?")
                stopdata["routeid"] = route.get("iconDisplayText", "?")
                if len(self._routes) != 0 and stopdata["routeid"] not in self._routes:
                    continue
                stopdata["headsign"] = stopTime.get("stopHeadsign", "?")
                if (
                    len(self._headsigns) != 0
                    and stopdata["headsign"] not in self._headsigns
                ):
                    continue

                if tripid:
                    # Card fetches the route polyline on map open (keeps state small).
                    stopdata["tripId"] = tripid

                if attime:
                    stopdata["attime"] = datetime.fromtimestamp(
                        attime, self._tz
                    ).strftime("%H:%M")
                if predicted_attime:
                    stopdata["predicted_attime"] = datetime.fromtimestamp(
                        predicted_attime, self._tz
                    ).strftime("%H:%M")
                    if attime:
                        # positive = late, negative = early (seconds)
                        stopdata["delay"] = int(predicted_attime - attime)

                if stopTime.get("canceled"):
                    stopdata["canceled"] = True

                alert_ids = stopTime.get("alertIds") or []
                if alert_ids:
                    stopdata["alertIds"] = alert_ids
                    for alert_id in alert_ids:
                        add_alert(alert_id)

                if stopTime.get("requiresFirstDoorBoarding"):
                    stopdata["firstDoor"] = True
                if stopTime.get("mayRequireBooking"):
                    stopdata["booking"] = True

                wheelchair_val = stopTime.get("wheelchairAccessible")
                if wheelchair_val is None:
                    wheelchair_val = trip.get("wheelchairAccessible")
                if self._wheelchair and wheelchair_val is not None:
                    stopdata["wheelchair"] = str(wheelchair_val)

                bikes_val = trip.get("bikesAllowed")
                if bikes_val is None:
                    bikes_val = route.get("bikesAllowed")
                if self._bikes and bikes_val is not None:
                    # Keep both keys: card historically expected bikesAllowed
                    stopdata["bikesallowed"] = bikes_val
                    stopdata["bikesAllowed"] = bikes_val

                if self._colors:
                    color = route.get("color")
                    text_color = route.get("textColor")
                    # Normalize rail colors to MÁV START / Budapest GO 2026 branding
                    route_text = stopdata["routeid"]
                    if stopdata["type"] == "RAIL" and route_text:
                        if re.match(r"^Z\d+", route_text, re.I):
                            color, text_color = "FFCD28", "3C3C3C"
                        elif re.match(r"^G\d+", route_text, re.I):
                            color, text_color = "AACD46", "FFFFFF"
                        elif re.match(r"^S\d+", route_text, re.I):
                            color, text_color = "00AFF0", "FFFFFF"
                        elif route_text.upper() == "IR":
                            color, text_color = "008000", "FFFFFF"
                        elif route_text.upper() in (
                            "IC",
                            "EC",
                            "EN",
                            "EX",
                            "RJX",
                            "S",
                            "SZ",
                        ):
                            color, text_color = "2E5EA8", "FFFFFF"
                    if color:
                        stopdata["color"] = color
                    if text_color:
                        stopdata["textcolor"] = text_color

                vehicle = stopTime.get("vehicle")
                if self._vehicle and isinstance(vehicle, dict):
                    if vehicle.get("model"):
                        stopdata["model"] = vehicle["model"]
                    if vehicle.get("licensePlate"):
                        stopdata["licensePlate"] = vehicle["licensePlate"]
                    if vehicle.get("status"):
                        stopdata["vehicleStatus"] = vehicle["status"]
                    if vehicle.get("stopDistancePercent") is not None:
                        stopdata["distancePercent"] = vehicle["stopDistancePercent"]
                    occupancy = vehicle.get("occupancy") or vehicle.get("capacity")
                    if isinstance(occupancy, dict) and occupancy:
                        stopdata["occupancy"] = occupancy
                    if vehicle.get("wheelchairAccessible") is not None and self._wheelchair:
                        stopdata["wheelchair"] = str(vehicle["wheelchairAccessible"])
                    location = vehicle.get("location") or {}
                    lat = location.get("lat")
                    lon = location.get("lon")
                    if lat is not None and lon is not None:
                        try:
                            stopdata["lat"] = float(lat)
                            stopdata["lon"] = float(lon)
                        except (TypeError, ValueError):
                            pass
                    if vehicle.get("bearing") is not None:
                        try:
                            stopdata["bearing"] = float(vehicle["bearing"])
                        except (TypeError, ValueError):
                            pass
                    if vehicle.get("label"):
                        stopdata["vehicleLabel"] = vehicle["label"]
                    if vehicle.get("vehicleId"):
                        stopdata["vehicleId"] = vehicle["vehicleId"]

                self._apply_elvira_track(stopdata)

                bkkjson["vehicles"].append(stopdata)
                if int(self._maxitems) > 0:
                    itemnr += 1
                    if itemnr >= int(self._maxitems):
                        break

        dt_now = datetime.now()
        bkkjson["updatedAt"] = dt_now.strftime("%Y/%m/%d %H:%M")
        if bkkjson["vehicles"]:
            self._state = bkkjson["vehicles"][0]["in"]
        else:
            self._state = None

        return bkkjson

    def _compute_state_from_data(self):
        """Derive sensor state without relying on attribute side-effects."""
        bkkdata = self._bkkdata
        if "status" not in bkkdata or bkkdata["status"] != "OK":
            return None
        if "data" not in bkkdata:
            return None
        entry = bkkdata["data"].get("entry") or {}
        stop_times = entry.get("stopTimes") or []
        if not stop_times:
            return None

        refs = bkkdata["data"].get("references") or {}
        currenttime = int(bkkdata["currentTime"] / 1000)
        for stopTime in stop_times:
            attime = stopTime.get("departureTime")
            predicted_attime = stopTime.get("predictedDepartureTime")
            diff = int(((attime or 0) - currenttime) / 60)
            if self._inpredicted and predicted_attime:
                diff = int((predicted_attime - currenttime) / 60)
            if diff < 0:
                diff = 0
            if self._ignorenow and diff == 0 and not stopTime.get("canceled"):
                continue

            tripid = stopTime.get("tripId")
            trip = (refs.get("trips") or {}).get(tripid) or {}
            routeid = trip.get("routeId")
            route = (refs.get("routes") or {}).get(routeid) or {}
            route_text = route.get("iconDisplayText", "?")
            headsign = stopTime.get("stopHeadsign", "?")
            if self._routes and route_text not in self._routes:
                continue
            if self._headsigns and headsign not in self._headsigns:
                continue
            return str(diff)
        return None

    async def async_update(self):
        _session = async_get_clientsession(self._hass)

        _LOGGER.debug("bkk_stop update for %s", self._stopid)
        params = [
            f"key={self._apikey}",
            "version=4",
            "appVersion=apiary-1.0",
            "onlyDepartures=true",
            f"stopId={self._stopid}",
            f"minutesAfter={self._minsafter}",
            f"minutesBefore={self._minsbefore}",
            "includeReferences=true",
        ]
        if self._vehicle:
            params.append("includeVehicleFromTrip=true")
        BKKURL = (
            "https://go.bkk.hu/api/query/v1/ws/otp/api/where/"
            "arrivals-and-departures-for-stop.json?" + "&".join(params)
        )

        success = False
        last_error = None
        for i in range(MAX_RETRIES):
            try:
                async with _session.get(BKKURL, timeout=HTTP_TIMEOUT) as response:
                    payload = await response.json(content_type=None)

                if response.status // 100 != 2:
                    last_error = f"HTTP {response.status}"
                    _LOGGER.debug(
                        "Fetch attempt %s: unexpected response %s",
                        i + 1,
                        response.status,
                    )
                    await self._hass.async_add_executor_job(_sleep, 10)
                    continue

                if not isinstance(payload, dict) or payload.get("status") != "OK":
                    status = (
                        payload.get("status")
                        if isinstance(payload, dict)
                        else type(payload).__name__
                    )
                    last_error = f"API status: {status}"
                    _LOGGER.debug(
                        "Fetch attempt %s: non-OK API status %s", i + 1, status
                    )
                    await self._hass.async_add_executor_job(_sleep, 10)
                    continue

                self._bkkdata = payload
                success = True
                break
            except Exception as err:
                last_error = f"{type(err).__name__}: {err}"
                _LOGGER.debug("Fetch attempt %s failed for %s", i + 1, self._stopid)
                _LOGGER.error("error: %s of type: %s", err, type(err))
                await self._hass.async_add_executor_job(_sleep, 10)

        self._track_api_result(success, last_error)

        # Trip shapes are fetched by the Lovelace card on demand (CORS OK on
        # go.bkk.hu). Prefetching ~12×220 points bloated entity state (~50KB+)
        # and often left the frontend with a stale custom element that never
        # drew the preloaded polyline.
        self._shapes = {}

        if success and self._elvira_station:
            try:
                rows, havaria = await _fetch_elvira_departures(
                    _session,
                    self._hass,
                    self._elvira_station,
                    self._minsafter,
                )
                self._elvira_rows = rows
                self._elvira_havaria = havaria
                self._elvira_ok = True
                _LOGGER.debug(
                    "ELVIRA tracks for %s (%s): %s rows, %s havaria",
                    self.entity_id,
                    self._elvira_station,
                    len(rows),
                    len(havaria),
                )
            except Exception as err:
                self._elvira_ok = False
                _LOGGER.debug(
                    "ELVIRA enrichment failed for %s: %s", self._stopid, err
                )
        elif not self._elvira_station:
            self._elvira_rows = []
            self._elvira_havaria = []
            self._elvira_ok = None

        self._state = self._compute_state_from_data()
        _LOGGER.debug("bkk_stop updated for %s: %s", self._stopid, self._state)
        return self._state

    async def _load_shapes(self, session):
        """Prefetch trip shapes for mapable vehicles (GPS and/or rail)."""
        bkkdata = self._bkkdata
        if not isinstance(bkkdata, dict) or bkkdata.get("status") != "OK":
            return {}
        data = bkkdata.get("data") or {}
        entry = data.get("entry") or {}
        refs = data.get("references") or {}
        trips_ref = refs.get("trips") or {}
        routes_ref = refs.get("routes") or {}
        wanted = []
        for stop_time in entry.get("stopTimes") or []:
            trip_id = stop_time.get("tripId")
            if not trip_id:
                continue
            trip = trips_ref.get(trip_id) or {}
            route = routes_ref.get(trip.get("routeId")) or {}
            route_text = route.get("iconDisplayText", "?")
            headsign = stop_time.get("stopHeadsign", "?")
            if self._routes and route_text not in self._routes:
                continue
            if self._headsigns and headsign not in self._headsigns:
                continue
            vehicle = stop_time.get("vehicle") if self._vehicle else None
            loc = (vehicle or {}).get("location") or {}
            has_gps = loc.get("lat") is not None and loc.get("lon") is not None
            is_rail = str(route.get("type") or "").upper() == "RAIL"
            if has_gps or is_rail:
                wanted.append(trip_id)

        # Preserve order, unique, cap
        unique = list(dict.fromkeys(wanted))[:SHAPE_FETCH_LIMIT]
        if not unique:
            return {}

        shapes = {}
        # Sequential is safer for BKK rate limits; cache makes later polls cheap
        for trip_id in unique:
            shape = await _fetch_trip_shape(
                session, self._hass, self._apikey, trip_id
            )
            if shape:
                shapes[trip_id] = shape
        _LOGGER.debug(
            "loaded %s/%s trip shapes for %s",
            len(shapes),
            len(unique),
            self.entity_id,
        )
        return shapes

    @property
    def name(self):
        return self._name

    @property
    def native_value(self) -> object:
        """Return the state of the sensor."""
        return self._state

    @property
    def state(self):
        return self._state

    @property
    def unique_id(self) -> str:
        return self.entity_id

    def __repr__(self) -> str:
        """Return main sensor parameters."""
        return (
            f"{self.__class__.__name__}(name={self._name}, "
            f"entity_id={self.entity_id}, "
            f"state={self.state}, "
            f"attributes={self.extra_state_attributes})"
        )
