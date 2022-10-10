import aiohttp
import asyncio
from datetime import timedelta
from datetime import datetime
import logging

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import ATTR_ATTRIBUTION, CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity

REQUIREMENTS = [ ]

_LOGGER = logging.getLogger(__name__)

CONF_ATTRIBUTION = "Data provided by futar.bkk.hu"
CONF_BIKES = 'bikes'
CONF_IGNORENOW = 'ignoreNow'
CONF_MINSAFTER = 'minsAfter'
CONF_MAXITEMS = 'maxItems'
CONF_STOPID = 'stopId'
CONF_WHEELCHAIR = 'wheelchair'
CONF_FAVORITES = 'favorites'

DEFAULT_NAME = 'BKK Futar'
DEFAULT_ICON = 'mdi:bus'

SCAN_INTERVAL = timedelta(seconds=30)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_STOPID): cv.string,
    vol.Optional(CONF_MAXITEMS, default=0): cv.string,
    vol.Optional(CONF_MINSAFTER, default=20): cv.string,
    vol.Optional(CONF_WHEELCHAIR, default=False): cv.boolean,
    vol.Optional(CONF_BIKES, default=False): cv.boolean,
    vol.Optional(CONF_IGNORENOW, default='true'): cv.boolean,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_FAVORITES, default=0): cv.string,
})

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):

    name = config.get(CONF_NAME)
    stopid = config.get(CONF_STOPID)
    maxitems = config.get(CONF_MAXITEMS)
    minsafter = config.get(CONF_MINSAFTER)
    wheelchair = config.get(CONF_WHEELCHAIR)
    bikes = config.get(CONF_BIKES)
    ignorenow = config.get(CONF_IGNORENOW)
    favorites = config.get(CONF_FAVORITES)

    async_add_devices(
        [BKKPublicTransportSensor(hass, name, stopid, minsafter, wheelchair, bikes, ignorenow, maxitems, favorites)],update_before_add=True)

class BKKPublicTransportSensor(Entity):

    def __init__(self, hass, name, stopid, minsafter, wheelchair, bikes, ignorenow, maxitems, favorites):
        """Initialize the sensor."""
        self._name = name
        self._hass = hass
        self._stopid = stopid
        self._maxitems = maxitems
        self._minsafter = minsafter
        self._wheelchair = wheelchair
        self._bikes = bikes
        self._ignorenow = ignorenow
        self._favorites = favorites
        self._favoritestime = None
        self._state = None
        self._bkkdata = {}
        self._icon = DEFAULT_ICON
        self._session = async_get_clientsession(self._hass)

    @property
    def extra_state_attributes(self):
        bkkjson = {}
        bkkdata = self._bkkdata
        itemnr = 0

        if bkkdata["status"] != "OK":
          return None

        bkkjson["stationName"] = bkkdata["data"]["references"]["stops"][self._stopid]["name"]
        bkkjson["vehicles"] = []
        bkkjson["nextfavorite"] = ""
        bkkjson["nextfavoritetime"] = ""
        bkkjson["nextfavorite_unit_of_measurement"] = " min"
        failedNode = 0

        if len(bkkdata["data"]["entry"]["stopTimes"]) != 0:
          currenttime = int(bkkdata["currentTime"] / 1000)

          for stopTime in bkkdata["data"]["entry"]["stopTimes"]:
            diff = 0
            diff = int(( stopTime.get("departureTime", 0) - currenttime ) / 60)
            if diff < 0:
               diff = 0
            if self._ignorenow and diff == 0:
               continue

            tripid = stopTime.get("tripId")
            routeid = bkkdata["data"]["references"]["trips"][tripid]["routeId"]
            attime = stopTime.get("departureTime")
            predicted_attime = stopTime.get("predictedDepartureTime")

            stopdata = {}
            stopdata["in"] = str(diff)
            stopdata["type"] = bkkdata["data"]["references"]["routes"][routeid]["type"]
            stopdata["routeid"] = bkkdata["data"]["references"]["routes"][routeid]["iconDisplayText"]
            if len(bkkjson["nextfavorite"]) == 0 and (stopdata["routeid"] in self._favorites or self._favorites == 0):
                bkkjson["nextfavorite"] = stopdata["routeid"]
                bkkjson["nextfavoritetime"] = stopdata["in"]
                self._favoritestime = stopdata["in"]
            stopdata["headsign"] = stopTime.get("stopHeadsign","?")
            stopdata["attime"] = datetime.fromtimestamp(attime).strftime('%H:%M')
            if predicted_attime:
                stopdata["predicted_attime"] = datetime.fromtimestamp(predicted_attime).strftime('%H:%M')

            if self._wheelchair:
               if 'wheelchairAccessible' in bkkdata["data"]["references"]["trips"][tripid]:
                  stopdata["wheelchair"] = str(bkkdata["data"]["references"]["trips"][tripid]["wheelchairAccessible"])

            if self._bikes:
               if 'bikesAllowed' in bkkdata["data"]["references"]["trips"][tripid]:
                  stopdata["bikesallowed"] = bkkdata["data"]["references"]["trips"][tripid]["bikesAllowed"]

            bkkjson["vehicles"].append(stopdata)
            if int(self._maxitems) > 0:
               itemnr += 1
               if itemnr >= int(self._maxitems):
                  break

        return bkkjson

    @asyncio.coroutine
    async def async_update(self):
        _LOGGER.debug("bkk_stop update for " + self._stopid)
##        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.3'}
#        BKKURL="http://futar.bkk.hu/bkk-utvonaltervezo-api/ws/otp/api/where/arrivals-and-departures-for-stop.json?key=apaiary-test&version=3&appVersion=apiary-1.0&onlyDepartures=true&stopId=" + self._stopid + "&minutesAfter=" + self._minsafter
#       As of 2019-07-02 upgrade:
        BKKURL="https://futar.bkk.hu/api/query/v1/ws/otp/api/where/arrivals-and-departures-for-stop.json?key=apaiary-test&version=3&appVersion=apiary-1.0&onlyDepartures=true&stopId=" + self._stopid + "&minutesAfter=" + self._minsafter

        async with self._session.get(BKKURL) as response:
          self._bkkdata = await response.json()

        if self._bkkdata["status"] != "OK":
           self._state = None

        if len(self._bkkdata["data"]["entry"]["stopTimes"]) == 0:
           self._state = None
        self._state = 1
        return self._state

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._favoritestime
