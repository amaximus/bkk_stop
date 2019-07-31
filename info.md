# BKK Stop Information Component for Home Assistant
Show issues, pull requests, and more for your github repositories

<img src='https://raw.githubusercontent.com/amaximus/bkk_stop/master/example/bkk_lovelace.jpg' />

## Installation
Install this custom component and its related Lovelace custom card through
[HACS](https://github.com/custom-components/hacs).<br />
Its related Lovelace custom card can be found at
[https://github.com/amaximus/bkk_stop_card](https://github.com/amaximus/bkk_stop_card/).
<p>
After installation add the following to resources in your Lovelace config:

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
