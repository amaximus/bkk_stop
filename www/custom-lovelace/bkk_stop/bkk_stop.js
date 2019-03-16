class BkkStop extends HTMLElement {
  set hass(hass) {
    if (!this.content) {
      const card = document.createElement('ha-card');
      card.header = 'BKK Futár';
      //card.header = state.attributes.stationName;;
      this.content = document.createElement('div');
      this.content.style.padding = '0 16px 16px';
      card.appendChild(this.content);
      this.appendChild(card);
    }

    const entityId = this.config.entity;
    const state = hass.states[entityId];
    const stateStr = state ? state.state : 'unavailable';
    const stationname = state.attributes.stationName;
    
    let bkkObjN = [];
    
    var innerstring = `<b>${stationname}:</b><br><table width="100%">`;

    for (let i = 0; i < state.attributes.items; i++) {
      let element = {};
      element.headsign = eval('state.attributes.headsign' + i);
      element.routeid = eval('state.attributes.routeid' + i);
      element.rin = eval('state.attributes.in' + i);
      element.rtype = eval('state.attributes.type' + i);
      element.wheelchair = 'false';
      
      if (state.attributes.hasOwnProperty('wheelchair' + i)) {
        element.wheelchair = eval('state.attributes.wheelchair' + i);
      }
    
      element.bike = 'false';
      if (state.attributes.hasOwnProperty('bikesallowed' + i)) {
        element.bike = eval('state.attributes.bikesallowed' + i);
      }
      bkkObjN.push(element);
    }
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    //[ikon-járat] [kerekesszék] [kerékpár] [cél] [perc]
    
    for (let i = 0; i < state.attributes.items; i++) {
        var jarat = '<ha-icon icon="'+this.getIcon(bkkObjN[i].rtype)+'"></ha-icon>'+' '+bkkObjN[i].routeid;
        innerstring += '<tr><td>'+jarat+'</td><td>'+'</td><td>'+bkkObjN[i].headsign+'</td><td>'+bkkObjN[i].rin+'</td></tr>';
    }
    
    innerstring += '</table>';
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    /*innerstring += 
     `<b>${stationname}:</b><br>
      <ha-icon icon="mdi:bus"></ha-icon> 52 <ha-icon icon="mdi:wheelchair-accessibility"></ha-icon><ha-icon icon="mdi:bike"></ha-icon> P.erzsébet, Pacsirtatelep 9 perc<br>
      <ha-icon icon="mdi:tram"></ha-icon> 52 <ha-icon icon="mdi:wheelchair-accessibility" class="smallicon"></ha-icon><ha-icon icon="mdi:bike" class="smallicon"></ha-icon> P.erzsébet, Pacsirtatelep 9 perc
      
      
    `;*/
    

    this.content.innerHTML = innerstring+'</table>';
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('You need to define an entity');
    }
    this.config = config;
  }

  // The height of your card. Home Assistant uses this to automatically
  // distribute all cards over the available columns. 
  getCardSize() {
    return 3;
  }
  
  getIcon(type) {
      if (type === "BUS") {
          return "mdi:bus"
      } else if (type === "TROLLEYBUS") {
          return "mdi:bus"
      } else if (type === "TRAM") {
          return "mdi:tram"
      } else if (type === "SUBWAY") {
          return "mdi:subway"
      } else if (type === "RAIL") {
          return "mdi:train"
      }
      return "mdi:bus"
  }
}

customElements.define('custom-bkk-stop', BkkStop);