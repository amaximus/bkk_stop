import aiohttp
import asyncio
from urllib.parse import urlencode
from datetime import timedelta
from datetime import datetime
import logging
import zoneinfo
import time
import voluptuous as vol

from homeassistant.core import ServiceCall
from homeassistant.components.sensor import PLATFORM_SCHEMA, ENTITY_ID_FORMAT
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    CONF_NAME,
    ATTR_ENTITY_ID,
    CONF_ENTITY_ID,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity, async_generate_entity_id

REQUIREMENTS = []

_LOGGER = logging.getLogger(__name__)

CONF_APIKEY = "apiKey"
CONF_ATTRIBUTION = "Data provided by go.bkk.hu"
CONF_BIKES = "bikes"
CONF_COLORS = "colors"
CONF_HEADSIGNS = "headsigns"
CONF_IGNORENOW = "ignoreNow"
CONF_INPREDICTED = "inPredicted"
CONF_MINSAFTER = "minsAfter"
CONF_MINRESULT = "minResult"
CONF_MAXITEMS = "maxItems"
CONF_ROUTES = "routes"
CONF_STOPID = "stopId"
CONF_MINSBEFORE = "minsBefore"
CONF_WHEELCHAIR = "wheelchair"

DEFAULT_NAME = "Budapest GO"
DEFAULT_ICON = "mdi:bus"
DOMAIN = "bkk_stop"
SENSOR_PLATFORM = "sensor"

REFRESH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): vol.All(cv.ensure_list, [cv.string]),
    }
)

HTTP_TIMEOUT = 60  # secs
MAX_RETRIES = 3
SCAN_INTERVAL = timedelta(seconds=120)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(ATTR_ENTITY_ID, default=""): cv.string,
        vol.Required(CONF_APIKEY): cv.string,
        vol.Required(CONF_STOPID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_BIKES, default=False): cv.boolean,
        vol.Optional(CONF_COLORS, default=False): cv.boolean,
        vol.Optional(CONF_HEADSIGNS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_IGNORENOW, default="true"): cv.boolean,
        vol.Optional(CONF_INPREDICTED, default="false"): cv.boolean,
        vol.Optional(CONF_MAXITEMS, default=0): cv.string,
        vol.Optional(CONF_MINSAFTER, default=20): cv.string,
        vol.Optional(CONF_MINRESULT, default=0): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_ROUTES, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_MINSBEFORE, default=0): cv.string,
        vol.Optional(CONF_WHEELCHAIR, default=False): cv.boolean,
    }
)


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):

    name = config.get(CONF_NAME)
    entityid = config.get(ATTR_ENTITY_ID)

    stopid = config.get(CONF_STOPID)
    maxitems = config.get(CONF_MAXITEMS)
    minsafter = config.get(CONF_MINSAFTER)
    minresult = config.get(CONF_MINRESULT)
    wheelchair = config.get(CONF_WHEELCHAIR)
    bikes = config.get(CONF_BIKES)
    colors = config.get(CONF_COLORS)
    ignorenow = config.get(CONF_IGNORENOW)
    routes = config.get(CONF_ROUTES)
    headsigns = config.get(CONF_HEADSIGNS)
    inpredicted = config.get(CONF_INPREDICTED)
    minsbefore = config.get(CONF_MINSBEFORE)
    apikey = config.get(CONF_APIKEY)

    async_add_devices(
        [
            BKKPublicTransportSensor(
                hass,
                name,
                entityid,
                stopid,
                minsafter,
                minresult,
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
            )
        ],
        update_before_add=True,
    )


def _sleep(secs):
    time.sleep(secs)


class BKKPublicTransportSensor(Entity):

    def __init__(
        self,
        hass,
        name,
        entityid,
        stopid,
        minsafter,
        minresult,
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
    ):

        async def handle_refresh(call: ServiceCall) -> None:
            """Handle the refresh service call."""
            for target_id in call.data[CONF_ENTITY_ID]:
                entity = hass.data[DOMAIN][SENSOR_PLATFORM].get(target_id)
                if entity is None:
                    _LOGGER.warning("called refresh for unknown entity %s", target_id)
                    continue
                _LOGGER.debug("called refresh for %s", target_id)
                entity.async_schedule_update_ha_state(force_refresh=True)

        """Initialize the sensor."""
        self._name = name
        self._hass = hass
        self._stopid = stopid
        self._maxitems = maxitems
        self._minsafter = minsafter
        self._minresult = minresult
        self._wheelchair = wheelchair
        self._bikes = bikes
        self._colors = colors
        self._ignorenow = ignorenow
        self._inpredicted = inpredicted
        self._apikey = apikey
        self._routes = routes
        self._headsigns = headsigns
        self._minsbefore = minsbefore
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

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN].setdefault(SENSOR_PLATFORM, {})
        hass.data[DOMAIN][SENSOR_PLATFORM][self.entity_id] = self 
        hass.services.async_register(
            DOMAIN,
            "refresh",
            handle_refresh,
            schema=REFRESH_SCHEMA,
        )

    @property
    def extra_state_attributes(self):
        bkkjson = {}
        bkkdata = self._bkkdata
        itemnr = 0

        if "status" in bkkdata:
            if bkkdata["status"] != "OK":
                return None
        else:
            return None

        stationNames = sorted(
            {s["name"] for s in bkkdata["data"]["references"]["stops"].values()}
        )
        bkkjson["stationName"] = ", ".join(stationNames)
        vehicles = []

        if len(bkkdata["data"]["entry"]["stopTimes"]) != 0:
            currenttime = int(bkkdata["currentTime"] / 1000)

            for stopTime in bkkdata["data"]["entry"]["stopTimes"]:
                diff = 0
                diff = int((stopTime.get("departureTime", 0) - currenttime) / 60)
                if self._inpredicted and "predictedDepartureTime" in stopTime:
                    diff = int(
                        (stopTime.get("predictedDepartureTime", 0) - currenttime) / 60
                    )

                if diff < 0:
                    diff = 0
                if self._ignorenow and diff == 0:
                    continue

                tripid = stopTime.get("tripId")
                routeid = bkkdata["data"]["references"]["trips"][tripid]["routeId"]
                attime = stopTime.get("departureTime")
                predicted_attime = stopTime.get("predictedDepartureTime")

                stopdata = {}
                stopdata["in"] = diff
                stopdata["type"] = bkkdata["data"]["references"]["routes"][routeid][
                    "type"
                ]
                stopdata["routeid"] = bkkdata["data"]["references"]["routes"][routeid][
                    "iconDisplayText"
                ]
                if len(self._routes) != 0 and stopdata["routeid"] not in self._routes:
                    continue
                stopdata["headsign"] = stopTime.get("stopHeadsign", "?")
                if (
                    len(self._headsigns) != 0
                    and stopdata["headsign"] not in self._headsigns
                ):
                    continue
                stopdata["attime"] = datetime.fromtimestamp(attime, self._tz).strftime(
                    "%H:%M"
                )
                if predicted_attime:
                    stopdata["predicted_attime"] = datetime.fromtimestamp(
                        predicted_attime, self._tz
                    ).strftime("%H:%M")

                if self._wheelchair:
                    if (
                        "wheelchairAccessible"
                        in bkkdata["data"]["references"]["trips"][tripid]
                    ):
                        stopdata["wheelchair"] = str(
                            bkkdata["data"]["references"]["trips"][tripid][
                                "wheelchairAccessible"
                            ]
                        )

                if self._bikes:
                    if "bikesAllowed" in bkkdata["data"]["references"]["trips"][tripid]:
                        stopdata["bikesallowed"] = bkkdata["data"]["references"][
                            "trips"
                        ][tripid]["bikesAllowed"]

                if self._colors:
                    if "color" in bkkdata["data"]["references"]["routes"][routeid]:
                        stopdata["color"] = bkkdata["data"]["references"]["routes"][
                            routeid
                        ]["color"]
                    if "textColor" in bkkdata["data"]["references"]["routes"][routeid]:
                        stopdata["textcolor"] = bkkdata["data"]["references"]["routes"][
                            routeid
                        ]["textColor"]

                vehicles.append(stopdata)
                if int(self._maxitems) > 0:
                    itemnr += 1
                    if itemnr >= int(self._maxitems):
                        break

        bkkjson["vehicles"] = sorted(vehicles, key=lambda x: x["in"])
        dt_now = datetime.now()
        bkkjson["updatedAt"] = dt_now.strftime("%Y/%m/%d %H:%M")
        if len(bkkjson["vehicles"]) > 0:
            self._state = bkkjson["vehicles"][0]["in"]
        else:
            self._state = None

        return bkkjson

    async def async_update(self):
        _session = async_get_clientsession(self._hass)

        _LOGGER.debug("bkk_stop update for " + ",".join(self._stopid))
        params = {
            "key": self._apikey,
            "version": "3",
            "appVersion": "apiary-1.1",
            "onlyDepartures": "true",
            "stopId": (
                self._stopid if isinstance(self._stopid, list) else [self._stopid]
            ),
            "minutesAfter": self._minsafter,
            "minutesBefore": self._minsbefore,
            "minResult": self._minresult,
        }
        clean_params = {k: v for k, v in params.items() if v is not None}
        base_url = "https://go.bkk.hu/api/query/v1/ws/otp/api/where/arrivals-and-departures-for-stop.json"
        BKKURL = f"{base_url}?{urlencode(clean_params, doseq=True)}"

        for i in range(MAX_RETRIES):
            try:
                async with _session.get(BKKURL, timeout=HTTP_TIMEOUT) as response:
                    self._bkkdata = await response.json(content_type=None)

                if not response.status // 100 == 2:
                    _LOGGER.debug(
                        "Fetch attempt "
                        + str(i + 1)
                        + ": unexpected response "
                        + str(response.status)
                    )
                    await self._hass.async_add_executor_job(_sleep, 10)
                else:
                    break
            except Exception as err:
                _LOGGER.debug("Fetch attempt " + str(i + 1) + " failed for " + BKKURL)
                _LOGGER.error(f"error: {err} of type: {type(err)}")
                await self._hass.async_add_executor_job(_sleep, 10)

        if "status" in self._bkkdata:
            if self._bkkdata["status"] != "OK":
                self._state = None
        else:
            self._state = None

        if "data" in self._bkkdata:
            if len(self._bkkdata["data"]["entry"]["stopTimes"]) == 0:
                self._state = None
        else:
            self._state = None

        _LOGGER.debug(
            "bkk_stop updated for " + ",".join(self._stopid) + ": " + str(self._state)
        )

        return self._state

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
