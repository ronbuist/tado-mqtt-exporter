# tado-mqtt-exporter
A Python script to export Tado zone schedules with current setpoint, setpoint in 30 minutes and setpoint in 1 hour

## Background
I have an airconditioner that also has heating functionality. In an attempt to lower my natural gas consumption, I will use this to try to heat up the rooms in our house and I would like to follow the schedules that I have for each room in Tado. Tado controls the boiler of the central heating system. By heating the rooms prior to the schedule in Tado, I'm hoping to achieve this goal. I would like to maintain the schedules in one location: the Tado app. The Tado-MQTT-exporter is meant to provide sensors for Home Assistant that can be used in automations to control the AC.

## Exporter functionality
The Tado-MQTT-exporter has the following functionality:
* It logs onto the Tado API. The first time you run it, it will set up a token and you will need to visit a URL to confirm to Tado you want to give the script access to your Tado account (and schedules).
* For each zone you have configured in Tado, it will periodically publish the following data:
  * the current setpoint for the zone
  * the setpoint for the zone in 30 minutes from now
  * the setpoint for the zone in one hour from now
* For each zone, it will send Home Assistant MQTT discovery messages, allowing automatic setup of the three sensors for each zone.

## Prerequisites
Please make sure you have the [paho-mqtt](https://pypi.org/project/paho-mqtt/) and [pyton-tado (PyTado)](https://pypi.org/project/python-tado/) libraries installed.

## Virtual environment
I'm running this on a Raspberry Pi, which has a managed Python environment. Since there is no Debian package for installing PyTado, I have created a virtual environment and used Pip to install the libraries I needed.

## Service

```
[Unit]
Description=Tado MQTT Exporter
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/tado-mqtt-exporter
ExecStart=/bin/bash -c 'source /home/pi/tado-mqtt-exporter/.venv/bin/activate && exec python3 /home/pi/tado-mqtt-exporter/tado-mqtt-exporter.py -c /home/pi/tado-mqtt-exporter/config.yml'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

