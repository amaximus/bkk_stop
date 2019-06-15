class BKKStopCard extends HTMLElement {

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  version() { return "0.1.0"; }

  _getAttributes(hass, filter1) {
    var inmin = new Array();
    var routeid = new Array();
    var vehicle = new Array();
    var headsign = new Array();
    var wheelchair = new Array();
    var bikes = new Array();
    var icon = new Array();
    var routeobjarray = [];
    var station;
    var items;

    function _filterName(stateObj, pattern) {
      let parts;
      let attr_id;
      let attribute;

      if (typeof (pattern) === "object") {
        parts = pattern["key"].split(".");
        attribute = pattern["key"];
      } else {
        parts = pattern.split(".");
        attribute = pattern;
      }
      attr_id = parts[2];

      if (attr_id.indexOf('*') === -1) {
        return stateObj == attribute;
      }
      const regEx = new RegExp(`^${attribute.replace(/\*/g, '.*')}$`, 'i');
      return stateObj.search(regEx) === 0;
    }
 
    var supportedItems = 8;
    var filters1 = new Array();
    for (var k=0; k < supportedItems; k++) {
      filters1[k*6+0] = {key: "sensor." + filter1 + ".routeid" + k};
      filters1[k*6+1] = {key: "sensor."+ filter1 + ".type" + k};
      filters1[k*6+2] = {key: "sensor."+ filter1 + ".headsign" + k};
      filters1[k*6+3] = {key: "sensor."+ filter1 + ".in" + k};
      filters1[k*6+4] = {key: "sensor."+ filter1 + ".wheelchair" + k};
      filters1[k*6+5] = {key: "sensor."+ filter1 + ".bikes" + k};
    }
    filters1[supportedItems*6] = {key: "sensor." + filter1 + ".stationName"};
    filters1[supportedItems*6+1] = {key: "sensor." + filter1 + ".items"};

    const attributes = new Map();
    filters1.forEach((filter) => {
      const filters = [];

      filters.push(stateObj => _filterName(stateObj, filter));

      Object.keys(hass.states).sort().forEach(key => {
        Object.keys(hass.states[key].attributes).sort().forEach(attr_key => {
          if (filters.every(filterFunc => filterFunc(`${key}.${attr_key}`))) {
            attributes.set(`${key}.${attr_key}`, {
              value: `${hass.states[key].attributes[attr_key]} ${filter.unit||''}`.trim(),
            });
          }  
        });
      });
    });

    var attr = Array.from(attributes.keys());
    var re = /\d$/;
    attr.forEach(key => {
      var newkey = key.split('.')[2];

      if ( re.test(newkey) ) {
        var idx = newkey[newkey.length - 1];
        var name = newkey.slice(0, -1);
        switch (name) {
          case 'in':
            inmin[idx]=attributes.get(key).value;
            break;
          case 'routeid':
            routeid[idx]=attributes.get(key).value;
            break;
          case 'type':
            vehicle[idx]=attributes.get(key).value.toLowerCase();
            icon[idx]=attributes.get(key).value.toLowerCase();
            if (attributes.get(key).value.toLowerCase() == "trolleybus") {
              icon[idx]="bus"
            } else if (attributes.get(key).value.toLowerCase() == "rail") {
              icon[idx]="train"
            }
            break;
          case 'headsign':
            headsign[idx]=attributes.get(key).value;
            break;
          case 'wheelchair':
            wheelchair[idx]='';
            if ( attributes.get(key).value ) {
              wheelchair[idx]='<iron-icon icon="mdi:wheelchair-accessibility" class="extraic">';
            }
            break;
          case 'bikes':
            bikes[idx]='';
            if ( attributes.get(key).value ) {
              bikes[idx]='<iron-icon icon="mdi:bike" class="extraic">';
            }
            break;
        }
      } else if ( newkey == "stationName") {
        station = attributes.get(key).value;
      } else if ( newkey == "items") {
        items = attributes.get(key).value;
      }
    });
    if ( items > 0 ) {
      for (var i=0; i < items; i++) {
        if ( routeid[i] ) {
          if ( typeof wheelchair[i] == 'undefined' ) {
            wheelchair[i] = '';
          }
          if ( typeof bikes[i] == 'undefined' ) {
            bikes[i] = '';
          }
          routeobjarray.push({
            key: routeid[i],
            vehicle: vehicle[i],
            inmin: inmin[i],
            headsign: headsign[i],
            wheelchair: wheelchair[i],
            bikes: bikes[i],
            icon: icon[i],
            station:station
          });
        }
      }
    } else {
      routeobjarray.push({
        key: 'No service',
        vehicle: '',
        inmin: 'following',
        headsign: 'any destination',
        wheelchair: '',
        bikes: '',
        icon: '',
        station: station
      }); 
    }
    return Array.from(routeobjarray.values());
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('Please define an entity');
    }
    config.filter

    const root = this.shadowRoot;
    if (root.lastChild) root.removeChild(root.lastChild);

    const cardConfig = Object.assign({}, config);
    const card = document.createElement('ha-card');
    const content = document.createElement('div');
    const style = document.createElement('style');
    style.textContent = `
      h3 {
        text-align: center;
        padding-top:15px;
      }
      table {
        width: 100%;
        padding: 0px 36px 16px 0px;
        border: none;
        margin-left: 16px;
        margin-right: 16px;
      }
      thead th {
        text-align: left;
      }
      tbody tr:nth-child(odd) {
        background-color: var(--paper-card-background-color);
        vertical-align: middle;
      }
      tbody tr:nth-child(even) {
        background-color: var(--secondary-background-color);
      }
      td {
        padding-left: 5px;
      }
      .emp {
         font-weight: bold;
         font-size: 120%;
      }
      .extraic {
         width: 1em;
         padding-left: 5px;
      }
      .bus {
         color: #44739e;
         width: 0.1em;
      }
      .trolleybus {
         color: #cc0000;
         width: 1.5em;
      }
      .tram {
         color: #e1e100;
         width: 1.5em;
      }
      .rail {
         color: #2ecc71;
         width: 1.5em;
      }
      .subway {
         width: 1.5em;
      }
    `;
    content.innerHTML = `
      <p id='station'>
      <table>
        <tbody id='attributes'>
        </tbody>
      </table>
    `;
    card.appendChild(style);
    card.appendChild(content);
    root.appendChild(card)
    this._config = cardConfig;
  }

  _updateContent(element, attributes) {
    element.innerHTML = `
      ${attributes.map((attribute) => `
        <tr>
          <td class="${attribute.vehicle}"><iron-icon icon="mdi:${attribute.icon}"></td>
          <td><span class="emp">${attribute.key}</span> to ${attribute.headsign} in ${attribute.inmin} mins
          ${attribute.wheelchair}${attribute.bikes}</td>
        </tr>
      `).join('')}
    `;
  }

  _updateStation(element, attributes) {
    element.innerHTML = `
      ${attributes.map((attribute) => `
        <h3>${attribute.station}</h3>
      `)[0]}
    `;
  }

  set hass(hass) {
    const config = this._config;
    const root = this.shadowRoot;

    let attributes = this._getAttributes(hass, config.entity.split(".")[1]);

    this._updateStation(root.getElementById('station'), attributes);
    this._updateContent(root.getElementById('attributes'), attributes);
  }

  getCardSize() {
    return 1;
  }
}

customElements.define('bkk-stop-card', BKKStopCard);
