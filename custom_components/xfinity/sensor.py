import json
import logging
import requests
import voluptuous as vol

from datetime import timedelta
from re import search

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    CONF_NAME,
    CONF_USERNAME,
    CONF_PASSWORD,
    EVENT_HOMEASSISTANT_START)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity

from .const import *


_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
})


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Setup the sensor platform."""
    name = config.get(CONF_NAME)
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)

    xfinity_data = XfinityUsageData(username, password)
    sensor = XfinityUsageSensor(name, xfinity_data)

    def _first_run():
        sensor.update()
        add_entities([sensor])

    # Wait until start event is sent to load this component.
    hass.bus.listen_once(EVENT_HOMEASSISTANT_START, lambda _: _first_run())


class XfinityUsageSensor(Entity):
    """Representation of the Xfinity Usage sensor."""

    def __init__(self, name, xfinity_data):
        """Initialize the sensor."""
        self._name = name
        self._icon = DEFAULT_ICON
        self._xfinity_data = xfinity_data
        self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return self._icon

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._xfinity_data.total_usage is not None:
            return self._xfinity_data.total_usage

    @property
    def device_state_attributes(self):
        """Return the state attributes of the last update."""
        if self._xfinity_data.total_usage is None:
            return None

        res = self._xfinity_data.data
        res[ATTR_ATTRIBUTION] = ATTRIBUTION
        res[ATTR_TOTAL_USAGE] = self._xfinity_data.total_usage
        res[ATTR_ALLOWED_USAGE] = self._xfinity_data.allowed_usage
        res[ATTR_REMAINING_USAGE] = self._xfinity_data.remaining_usage
        res[ATTR_POLICY_NAME] = str(self._xfinity_data.policy_name).capitalize()
        return res

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        if self._xfinity_data.unit is not None:
            return self._xfinity_data.unit

    def update(self):
        """Fetch new state data for the sensor."""
        self._xfinity_data.update()


class XfinityUsageData:
    """Xfinity Usage data object"""

    def __init__(self, username, password):
        """Setup usage data object"""
        self.session = requests.Session()
        self.username = username
        self.password = password
        self.data = None
        self.unit = None
        self.total_usage = None
        self.allowed_usage = None
        self.remaining_usage = None
        self.policy_name = None
        self._policy = None

    def update(self):
        """Update usage values"""
        _LOGGER.debug("Finding reqId for login...")
        res = self.session.get('https://customer.xfinity.com/oauth/force_connect/?continue=%23%2Fdevices')
        if res.status_code != 200:
            _LOGGER.error(f"Failed to find reqId, status_code:{res.status_code}")
            return

        m = search(r'<input type="hidden" name="reqId" value="(.*?)">', res.text)
        req_id = m.group(1)
        _LOGGER.debug(f"Found reqId = {req_id}")

        data = {
          'user': self.username,
          'passwd': self.password,
          'reqId': req_id,
          'deviceAuthn': 'false',
          's': 'oauth',
          'forceAuthn': '1',
          'r': 'comcast.net',
          'ipAddrAuthn': 'false',
          'continue': 'https://oauth.xfinity.com/oauth/authorize?client_id=my-account-web&prompt=login&redirect_uri=https%3A%2F%2Fcustomer.xfinity.com%2Foauth%2Fcallback&response_type=code&state=%23%2Fdevices&response=1',
          'passive': 'false',
          'client_id': 'my-account-web',
          'lang': 'en',
        }

        _LOGGER.debug("Posting to login...")
        res = self.session.post('https://login.xfinity.com/login', data=data)
        if res.status_code != 200:
            _LOGGER.error(f"Failed to login, status_code:{res.status_code}")
            _LOGGER.debug(f"Failed response: {res}")
            return

        _LOGGER.debug("Fetching internet usage AJAX...")
        res = self.session.get('https://customer.xfinity.com/apis/services/internet/usage')
        if res.status_code != 200:
            _LOGGER.error(f"Failed to fetch data, status_code:{res.status_code}")
            return

        self.data = json.loads(res.text)
        _LOGGER.debug(f"Received usage data: {self.data}")

        try:
            self._policy = self.data['usageMonths'][-1]['policy']
            self.policy_name = str(self.data['usageMonths'][-1]['policyName']).capitalize()
            self.unit = self.data['usageMonths'][-1]['unitOfMeasure']
            self.total_usage = self.data['usageMonths'][-1]['homeUsage']
            if self._policy != 'unlimited':
                self.allowed_usage = self.data['usageMonths'][-1]['allowableUsage']
                self.remaining_usage = self.allowed_usage - self.total_usage

        except Exception as e:
            _LOGGER.error(f"Failed to set custom attrs, err: {e}")

        return
