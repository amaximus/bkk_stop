import aiohttp
import asyncio
from datetime import timedelta
from datetime import datetime
import logging
import pytz
import time
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, ENTITY_ID_FORMAT
from homeassistant.const import ATTR_ATTRIBUTION, CONF_NAME, ATTR_ENTITY_ID
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity, async_generate_entity_id

REQUIREMENTS = [ ]

_LOGGER = logging.getLogger(__name__)

CONF_APIKEY = 'apiKey'
CONF_ATTRIBUTION = "Data provided by go.bkk.hu"
CONF_BIKES = 'bikes'
CONF_COLORS = 'colors'
CONF_HEADSIGNS = 'headsigns'
CONF_IGNORENOW = 'ignoreNow'
CONF_INPREDICTED = 'inPredicted'
CONF_MINSAFTER = 'minsAfter'
CONF_MAXITEMS = 'maxItems'
CONF_ROUTES = 'routes'
CONF_STOPID = 'stopId'
CONF_MINSBEFORE = 'minsBefore'
CONF_WHEELCHAIR = 'wheelchair'

DEFAULT_NAME = 'Budapest GO'
DEFAULT_ICON = 'mdi:bus'

HTTP_TIMEOUT = 60 # secs
MAX_RETRIES = 3
SCAN_INTERVAL = timedelta(seconds=120)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(ATTR_ENTITY_ID, default=''): cv.string,
    vol.Required(CONF_APIKEY): cv.string,
    vol.Required(CONF_STOPID): cv.string,
    vol.Optional(CONF_BIKES, default=False): cv.boolean,
    vol.Optional(CONF_COLORS, default=False): cv.boolean,
    vol.Optional(CONF_HEADSIGNS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_IGNORENOW, default='true'): cv.boolean,
    vol.Optional(CONF_INPREDICTED, default='false'): cv.boolean,
    vol.Optional(CONF_MAXITEMS, default=0): cv.string,
    vol.Optional(CONF_MINSAFTER, default=20): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_ROUTES, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_MINSBEFORE, default=0): cv.string,
    vol.Optional(CONF_WHEELCHAIR, default=False): cv.boolean,
})

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

    async_add_devices(
        [BKKPublicTransportSensor(hass, name, entityid, stopid, minsafter, wheelchair, bikes, colors, ignorenow, maxitems, routes, inpredicted, apikey, headsigns, minsbefore)],update_before_add=True)

def _sleep(secs):
    time.sleep(secs)

class BKKPublicTransportSensor(Entity):

    def __init__(self, hass, name, entityid, stopid, minsafter, wheelchair, bikes, colors, ignorenow, maxitems, routes, inpredicted, apikey, headsigns, minsbefore):
        """Initialize the sensor."""
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
        self._state = None
        self._bkkdata = {}
        self._tz = pytz.timezone(hass.config.time_zone)
        self._icon = DEFAULT_ICON
        if entityid == '':
          self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, name, None, hass)
        else:
          self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, entityid, None, hass)

    @property
    def extra_state_attributes(self):
        bkkjson = {}
        bkkdata = self._bkkdata
        itemnr = 0

        if 'status' in bkkdata:
           if bkkdata["status"] != "OK":
              return None
        else:
              return None

        bkkjson["stationName"] = bkkdata["data"]["references"]["stops"][self._stopid]["name"]
        bkkjson["vehicles"] = []
        failedNode = 0

        if len(bkkdata["data"]["entry"]["stopTimes"]) != 0:
          currenttime = int(bkkdata["currentTime"] / 1000)

          for stopTime in bkkdata["data"]["entry"]["stopTimes"]:
            diff = 0
            diff = int(( stopTime.get("departureTime", 0) - currenttime ) / 60)
            if self._inpredicted and 'predictedDepartureTime' in stopTime:
              diff = int(( stopTime.get("predictedDepartureTime", 0) - currenttime ) / 60)

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
            if len(self._routes) != 0 and stopdata["routeid"] not in self._routes:
              continue
            stopdata["headsign"] = stopTime.get("stopHeadsign","?")
            if len(self._headsigns) != 0 and stopdata["headsign"] not in self._headsigns:
              continue
            stopdata["attime"] = datetime.fromtimestamp(attime, self._tz).strftime('%H:%M')
            if predicted_attime:
                stopdata["predicted_attime"] = datetime.fromtimestamp(predicted_attime, self._tz).strftime('%H:%M')

            if self._wheelchair:
               if 'wheelchairAccessible' in bkkdata["data"]["references"]["trips"][tripid]:
                  stopdata["wheelchair"] = str(bkkdata["data"]["references"]["trips"][tripid]["wheelchairAccessible"])

            if self._bikes:
               if 'bikesAllowed' in bkkdata["data"]["references"]["trips"][tripid]:
                  stopdata["bikesallowed"] = bkkdata["data"]["references"]["trips"][tripid]["bikesAllowed"]

            if self._colors:
               if 'color' in bkkdata["data"]["references"]["routes"][routeid]:
                stopdata["color"] = bkkdata["data"]["references"]["routes"][routeid]["color"]
               if 'textColor' in bkkdata["data"]["references"]["routes"][routeid]:
                stopdata["textcolor"] = bkkdata["data"]["references"]["routes"][routeid]["textColor"]

            bkkjson["vehicles"].append(stopdata)
            if int(self._maxitems) > 0:
               itemnr += 1
               if itemnr >= int(self._maxitems):
                  break
        dt_now = datetime.now()
        bkkjson["updatedAt"] = dt_now.strftime("%Y/%m/%d %H:%M")

        return bkkjson

    async def async_update(self):
        _session = async_get_clientsession(self._hass)

        _LOGGER.debug("bkk_stop update for " + self._stopid)
        BKKURL="https://go.bkk.hu/api/query/v1/ws/otp/api/where/arrivals-and-departures-for-stop.json?key=" + self._apikey + "&version=3&appVersion=apiary-1.0&onlyDepartures=true&stopId=" + self._stopid + "&minutesAfter=" + self._minsafter + "&minutesBefore=" + self._minsbefore

        for i in range(MAX_RETRIES):
          try:
            async with _session.get(BKKURL, timeout=HTTP_TIMEOUT) as response:
              self._bkkdata = await response.json(content_type=None)

            if not response.status // 100 == 2:
              _LOGGER.debug("Fetch attempt " + str(i+1) + ": unexpected response " + str(response.status))
              await self._hass.async_add_executor_job(_sleep, 10)
            else:
              break
          except Exception as err:
              _LOGGER.debug("Fetch attempt " + str(i+1) + " failed for " + BKKURL)
              _LOGGER.error(f'error: {err} of type: {type(err)}')
              await self._hass.async_add_executor_job(_sleep, 10)

        self._state = 1

        if 'status' in self._bkkdata:
           if self._bkkdata["status"] != "OK":
              self._state = None
        else:
           self._state = None

        if 'data' in self._bkkdata:
           if len(self._bkkdata["data"]["entry"]["stopTimes"]) == 0:
              self._state = None
        else:
           self._state = None

        return self._state

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def unique_id(self) -> str:
        return self.entity_id
