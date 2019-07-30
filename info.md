# BKK Stop Information Component and Custom Card for Home Assistant
Show issues, pull requests, and more for your github repositories

<img src='https://raw.githubusercontent.com/amaximus/bkk_stop/master/example/bkk_lovelace.jpg' />

## Installation through [HACS](https://github.com/custom-components/hacs)
---
Add the following to resources in your Lovelace config:

```yaml
resources:
  - url: /community/bkk_stop/bkk_stop.js
    type: js
```

## Card Options
---
| Name | Type | Requirement | `Default` Description
| :---- | :---- | :------- | :----------- |
| entity | item | **Required** | sensor of bkk_stop type to display
---

## Card example
---
```yaml
type: custom:bkk_stop
entity:
  - sensor.bkk7u
type: custom:bkk_stop
entity:
  - sensor.bkkXu
```

## Component configuration
| Name | Type | Requirement | `Default` Description
| :---- | :---- | :------- | :----------- |
| name | string | **Optional** | `none` Name of component 
| stopId | string | **Required** | StopId as per futar.bkk.hu
| minsAfter | number | **Optional** | `20` Number of minutes ahead to show vehicles departing from station
| wheelchair | boolean | **Optional** | `false` Display vehicle's wheelchair accessibility
| bikes | boolean | **Optional** | `false` Display whether bikes are allowed on vehicle
| ignoreNow | boolean | **Optional** | `true` Ignore vehicles already in the station

## Example configuration
---
```yaml
platform: bkk_stop
name: 'bkk7u'
stopId: 'BKK_F00940'
minsAfter: 25
wheelchair: true
```
