# Custom component for Home Assistant
## BKK stop custom component
## Providing also a custom state card for legacyUI and a custom card for Lovelace

This custom component and custom card shows Budapest Public Transportation (BKK)
line information departing in the near future from a configurable stop.<p>

Lovelace UI does not support platform attributes natively.<br />
Inspired by [entity-attributes-card](https://github.com/custom-cards/entity-attributes-card)
on handling attributes in Lovelace, a Lovelace custom card was a dept and now made available for BKK Stop.

#### Installation
Easiest way to install it is through [HACS(Home Assistant Community Store)](https://custom-components.github.io/hacs/),
search for <i>BKK Stop Information</i> in the Integrations and under Plugins. Both are needed.<br />

If you are not using HACS, you may download bkk_stop.js for Lovelace and put it into $homeassistant_config_dir/www.<br />
If you are not using Lovelace please see below instructions for legacy UI.<br />
Also download the files from custom_components/bkk_stop into your $homeassistant_config_dir/custom_components/bkk_stop.<br />

Once downloaded and configured as per below information you'll need to restart HomeAssistant to have the custom component
and the sensors of bkk_stop platform taken into consideration.

#### Custom component configuration:
Define sensors with the following configuration parameters:<br />

**name** (Optional): Name of component<br />
**stopId** (Required): StopId as per [futar.bkk.hu](http://futar.bkk.hu)<br />
**minsAfter** (Optional): Number of minutes ahead to show vehicles departing from station (default: 20)<br />
**wheelchair** (Optional): Display vehicle's wheelchair accessibility (default: false)<br />
**bikes** (Optional): Display whether bikes are allowed on vehicle (default: false)<br />
**ignoreNow** (Optional): Ignore vehicles already in the station (default: true) <br />

#### Custom component example configuration
```
platform: bkk_stop
name: 'bkk7u'
stopId: 'BKK_F00940'
minsAfter: 25
wheelchair: true
```

#### Lovelace UI configuration
Add the following lines to your ui-lovelace.yaml (entity should be the sensor of bkk_stop platform you defined):
```
resources:
  - {type: module, url: '/www/community/bkk_stop/bkk_stop.js'}

    cards:
      - type: custom:bkk_stop
        entity: sensor.bkk7u
      - type: custom:bkk_stop
        entity: sensor.bkkxu
```

#### Legacy UI
Custom state card is provided for presenting data on legacy UI. Pls see the legacyUI directory structure for example.

Lovelace UI:<br />
![bkk_stop Lovelace example](example/bkk_lovelace.jpg)

Legacy UI:<br />
![bkk_stop legacy UI example](example/bkk_hass.jpg)
