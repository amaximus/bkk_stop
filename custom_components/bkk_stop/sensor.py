import asyncio
from datetime import timedelta
import logging
import urllib.request
import json

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import ATTR_ATTRIBUTION, CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity

REQUIREMENTS = [ "aiohttp==2.0.7" ]

_LOGGER = logging.getLogger(__name__)

CONF_ATTRIBUTION = "Data provided by futar.bkk.hu"
CONF_STOPID = 'stopId'
CONF_MINSAFTER = 'minsAfter'
CONF_WHEELCHAIR = 'wheelchair'
CONF_BIKES = 'bikes'
CONF_IGNORENOW = 'ignoreNow'

DEFAULT_NAME = 'BKK Futar'
DEFAULT_ICON = 'mdi:bus'

SCAN_INTERVAL = timedelta(seconds=120)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_STOPID): cv.string,
    vol.Optional(CONF_MINSAFTER, default=20): cv.string,
    vol.Optional(CONF_WHEELCHAIR, default=False): cv.boolean,
    vol.Optional(CONF_BIKES, default=False): cv.boolean,
    vol.Optional(CONF_IGNORENOW, default='true'): cv.boolean,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    #_LOGGER.debug("start async setup platform")

    name = config.get(CONF_NAME)
    stopid = config.get(CONF_STOPID)
    minsafter = config.get(CONF_MINSAFTER)
    wheelchair = config.get(CONF_WHEELCHAIR)
    bikes = config.get(CONF_BIKES)
    ignorenow = config.get(CONF_IGNORENOW)

    session = async_get_clientsession(hass)

    async_add_devices(
        [BKKPublicTransportSensor(name, stopid, minsafter, wheelchair, bikes, ignorenow)],update_before_add=True)

class BKKPublicTransportSensor(Entity):
    #attr = {}

    def __init__(self, name, stopid, minsafter, wheelchair, bikes, ignorenow):
        """Initialize the sensor."""
        self._name = name
        self._stopid = stopid
        self._minsafter = minsafter
        self._wheelchair = wheelchair
        self._bikes = bikes
        self._ignorenow = ignorenow
        self._state = None
        self._icon = DEFAULT_ICON

    @property
    def device_state_attributes(self):
        attr = {}
        bkkfile = "/tmp/" + self._stopid + ".json"
        bkkdata = json.load(open(bkkfile))

        if bkkdata["status"] != "OK":
           return None

        attr["stationName"] = bkkdata["data"]["references"]["stops"][self._stopid]["name"]
        attr["items"] = len(bkkdata["data"]["entry"]["stopTimes"])
        failedNode = 0
        if attr["items"] != 0:
          currenttime = int(bkkdata["currentTime"] / 1000)
          i = 0
          while i < len(bkkdata["data"]["entry"]["stopTimes"]) - failedNode:
            if 'departureTime' not in bkkdata["data"]["entry"]["stopTimes"][i + failedNode]:
               failedNode += 1
               continue

            diff = 0
            diff = int((bkkdata["data"]["entry"]["stopTimes"][i + failedNode]["departureTime"] - currenttime ) / 60)
            if diff < 0:
               diff = 0
            if self._ignorenow and diff == 0:
               failedNode += 1
               continue

            attr['in' + str(i)] = diff
            tripid = bkkdata["data"]["entry"]["stopTimes"][i + failedNode]["tripId"]
            routeid = bkkdata["data"]["references"]["trips"][tripid]["routeId"]
            attr['type' + str(i)] = bkkdata["data"]["references"]["routes"][routeid]["type"]
            attr['routeid' + str(i)] = bkkdata["data"]["references"]["routes"][routeid]["iconDisplayText"]
            attr['headsign' + str(i)] = bkkdata["data"]["entry"]["stopTimes"][i + failedNode]["stopHeadsign"]

            if self._wheelchair:
               if 'wheelchairAccessible' in bkkdata["data"]["references"]["trips"][tripid]:
                  attr['wheelchair' + str(i)] = str(bkkdata["data"]["references"]["trips"][tripid]["wheelchairAccessible"])

            if self._bikes:
               if 'bikesAllowed' in bkkdata["data"]["references"]["trips"][tripid]:
                  attr['bikesallowed' + str(i)] = bkkdata["data"]["references"]["trips"][tripid]["bikesAllowed"]

            i += 1
        attr["items"] = len(bkkdata["data"]["entry"]["stopTimes"]) - failedNode
        return attr

    @asyncio.coroutine
    def async_update(self):
        _LOGGER.debug("bkk_stop update for " + self._stopid)
##        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.3'}
#        BKKURL="http://futar.bkk.hu/bkk-utvonaltervezo-api/ws/otp/api/where/arrivals-and-departures-for-stop.json?key=apaiary-test&version=3&appVersion=apiary-1.0&onlyDepartures=true&stopId=" + self._stopid + "&minutesAfter=" + self._minsafter
#       As of 2019-07-02 upgrade:
        BKKURL="https://futar.bkk.hu/api/query/v1/ws/otp/api/where/arrivals-and-departures-for-stop.json?key=apaiary-test&version=3&appVersion=apiary-1.0&onlyDepartures=true&stopId=" + self._stopid + "&minutesAfter=" + self._minsafter
        bkkfile = "/tmp/" + self._stopid + ".json"

        opener = urllib.request.build_opener()
        opener.addheaders = [('User-agent', 'Mozilla/5.0')]
        urllib.request.install_opener(opener)
        urllib.request.urlretrieve(BKKURL, bkkfile)
        bkkdata = json.load(open(bkkfile))

        if bkkdata["status"] != "OK":
           self._state = None

        if len(bkkdata["data"]["entry"]["stopTimes"]) == 0:
           self._state = None
        self._state = 1
        return self._state  

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state
