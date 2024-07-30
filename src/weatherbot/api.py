import collections
import json
import os

import requests
from telegram.helpers import escape_markdown

API_KEY = os.environ.get('API_KEY')
if API_KEY is None:
    import dotenv

    dotenv.load_dotenv()
    API_KEY = os.environ['API_KEY']

url_template = "https://api.weatherapi.com/v1/current.json?key={key}&q={q}&aqi=no"
Condition = collections.namedtuple('Condition', ['code', 'icon', 'text'])


def get(q: str) -> requests.Response:
    url = url_template.format(key=API_KEY, q=q)
    resp = requests.get(url)
    return resp


def get_condition(resp: requests.Response) -> Condition:
    json_dict = resp.json()
    condition = json_dict['current']['condition']

    # return operator.itemgetter('code', 'icon', 'text')(condition)
    return Condition(**condition)  # same as above but return named tuple instead


def convert_direction(wind_degree: int) -> str:
    units = round(wind_degree / 45) % 8
    common_directions = "north northeast east southeast south southwest west northwest"
    return common_directions.title().split()[units]


def _numbered(decorated):
    global _current_number

    name = decorated.__name__
    num = _current_number
    _current_number *= 2
    _method_to_binary[name] = num
    return decorated


_current_number = 1
_method_to_binary = {}


class APIData:
    def __init__(self, json_dict: dict):
        self.json = json_dict
        self.state = 0b00011001  # Show location, condition, and temperature by default

    def __getitem__(self, item: str):
        keys = item.split('.')
        obj = self.json
        for key in keys:
            obj = obj[key]
        return obj

    def escape(self, item: str, entity_type: str = None) -> str:
        return escape_markdown(str(self[item]), version=2, entity_type=entity_type)

    @_numbered
    def location(self) -> str:
        return "*{country}, {region}*\n".format(country=self.escape('location.country'),
                                                region=self.escape('location.region'))

    @_numbered
    def localtime(self) -> str:
        return "⌛ *Local time*:  `{localtime}` {emoji}".format(localtime=self.escape('location.localtime', 'code'),
                                                                emoji=('☀️' if self['current.is_day'] else '🌑'))

    @_numbered
    def lat_long(self) -> str:
        return "🌐 *Latitude*: `{lat}`, *Longitude*: `{lon}`".format(lat=self.escape('location.lat', 'code'),
                                                                     lon=self.escape('location.lon', 'code'))

    @_numbered
    def condition(self) -> str:
        return "♾️ *Condition* is _{text}_".format(text=self.escape('current.condition.text'))

    @_numbered
    def temperature(self) -> str:
        return r"🌡️ *Temperature* `{c}°C` \(`{f}°F`\)".format(c=self.escape('current.temp_c', 'code'),
                                                              f=self.escape('current.temp_f', 'code'))

    @_numbered
    def wind(self) -> str:
        return (
            r"💨 *Wind* __speed__ is `{mph} miles/hour` \(`{kph} km/h`\) in the `{dir}` __direction__"
            .format(mph=self.escape('current.wind_mph', 'code'),
                    kph=self.escape('current.wind_kph', 'code'),
                    dir=convert_direction(self['current.wind_degree'])))

    _display_names = {
        'wind': 'wind data',
        'temperature': 'temperature data',
        'condition': 'the condition',
        'lat_long': 'latitude and longitude',
        'localtime': 'local time',
        'location': 'the location',
    }

    def __str__(self) -> str:
        text = ''
        for name, index in _method_to_binary.items():
            if self.state & index:
                method = getattr(self, name)
                text += method()
                text += '\n'
        return text

    def toggle(self, name: str) -> "ToggleSection":
        mask = _method_to_binary.get(name, 0)
        return ToggleSection(self, mask)

    @staticmethod
    def sections_names() -> tuple:
        return tuple(_method_to_binary)

    def sections(self) -> dict[str, bool]:
        return {name: bool(self.state & index) for name, index in _method_to_binary.items()}

    def normalize_section_name(self, method_name) -> str:
        return self._display_names.get(method_name, f'<Error (method={method_name})>')


class ToggleSection:
    def __init__(self, data: APIData, mask: int):
        self.data = data
        self.mask = mask

    def __call__(self):
        self.data.state ^= self.mask
        return self.data

    def to_json(self) -> str:
        d = dict(data=self.data.json,
                 state=self.data.state,
                 mask=self.mask)
        return json.dumps(d)

    @classmethod
    def from_json(cls, s: str) -> "ToggleSection":
        d = json.loads(s)
        data = APIData(d['data'])
        data.state = d['state']
        return cls(data, d['mask'])
