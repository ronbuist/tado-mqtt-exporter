import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import time as time_module

import yaml
import paho.mqtt.client as mqtt
from PyTado.interface.interface import Tado
from paho.mqtt.client import CallbackAPIVersion


logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("tado-mqtt-exporter")


def load_config(path: str):
    return yaml.safe_load(Path(path).read_text())


def mqtt_connect(cfg):
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    if cfg.get("username"):
        client.username_pw_set(cfg.get("username"), cfg.get("password"))
    client.connect(cfg.get("host", "localhost"), cfg.get("port", 1883))
    client.loop_start()
    return client


def publish_discovery(mqttc, base_topic, device_info, zone_name, sensor_key, sensor_name, unique_id, send_discovery):
    if not send_discovery:
        return
    topic = f"homeassistant/sensor/{base_topic}_{zone_name}_{sensor_key}/config"
    payload = {
        "name": sensor_name,
        "state_topic": f"{base_topic}/zone/{zone_name}/{sensor_key}/state",
        "unique_id": unique_id,
        "device": device_info,
        "unit_of_measurement": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "value_template": "{{ value | float }}",
    }
    mqttc.publish(topic, json.dumps(payload), retain=True)


def compute_future_setpoint(schedule, when_dt):
    if not schedule:
        return None

    target_time = when_dt.time()

    for block in schedule:
        start_hh, start_mm = map(int, block["start"].split(":"))
        end_hh, end_mm = map(int, block["end"].split(":"))

        from datetime import time as dt_time
        start_time = dt_time(start_hh, start_mm)
        end_time = dt_time(end_hh, end_mm)

        if start_time <= target_time < end_time:
            temp_data = block.get("setting", {}).get("temperature")
            if temp_data is None:
                return 0
            return temp_data.get("celsius", 0)

    temp_data = schedule[-1].get("setting", {}).get("temperature")
    if temp_data is None:
        return 0
    return temp_data.get("celsius", 0)


def export_loop(config_path):
    cfg = load_config(config_path)

    log_level_str = cfg.get("logging_level", "ERROR").upper()
    log_level = getattr(logging, log_level_str, logging.ERROR)
    logging.getLogger().setLevel(log_level)

    mqtt_cfg = cfg.get("mqtt", {})
    base_topic = mqtt_cfg.get("base_topic", "tado").lower().replace(" ", "_")
    token_file = cfg["tado"].get("token_file")
    interval = cfg.get("update_interval", 300)
    schedule_refresh_hours = cfg.get("schedule_refresh_hours", 8)
    zones_refresh_hours = cfg.get("zones_refresh_hours", 24)
    send_discovery = mqtt_cfg.get("send_discovery", True)

    mqttc = mqtt_connect(mqtt_cfg)

    tado = Tado(token_file_path=token_file)
    if tado.device_activation_status() == "PENDING":
        url = tado.device_verification_url()
        logger.error(f"Device activation pending. Please visit: {url}")
        tado.device_activation()
        status = tado.device_activation_status()
        if status == "COMPLETED":
            logger.info("TADO login successful")
        else:
            logger.error(f"TADO login failed. Status is {status}")
            return

    device_info = {
        "identifiers": ["tado_exporter"],
        "manufacturer": "tado",
        "model": "python-tado",
        "name": "Tado Exporter",
    }

    last_schedule_refresh = None
    last_zones_refresh = None
    schedules_per_zone = {}
    zones = []

    while True:
        now = datetime.now()

        # Zones refresh check
        if (last_zones_refresh is None) or ((now - last_zones_refresh).total_seconds() > zones_refresh_hours * 3600):
            zones = tado.get_zones()
            logger.info("Zones refreshed")
            logger.debug(f"Raw zones info: {zones}")
            last_zones_refresh = now

            # Discovery berichten verzenden
            for z in zones:
                zone_name_raw = z["name"]
                zone_name = zone_name_raw.lower().replace(" ", "_")
                for key, friendly in (
                    ("setpoint_now", "Setpoint (now)"),
                    ("setpoint_30m", "Setpoint (+30m)"),
                    ("setpoint_60m", "Setpoint (+60m)")
                ):
                    publish_discovery(
                        mqttc, base_topic, device_info, zone_name, key,
                        f"{zone_name_raw} {friendly}", f"tado_{zone_name}_{key}",
                        send_discovery
                    )

        # Schedule refresh check
        if (last_schedule_refresh is None) or ((now - last_schedule_refresh).total_seconds() > schedule_refresh_hours * 3600):
            schedules_per_zone.clear()
            for z in zones:
                zone_id = z["id"]
                zone_name_raw = z["name"]
                zone_name = zone_name_raw.lower().replace(" ", "_")

                try:
                    timetable_id = tado.get_timetable(zone_id)
                    schedule = tado.get_schedule(zone_id, timetable_id)
                    schedules_per_zone[zone_name] = schedule
                    logger.info(f"Schedule refreshed for zone '{zone_name_raw}'")
                    logger.debug(f"Raw schedule info: {schedule}")
                except Exception as e:
                    logger.error(f"Failed to refresh schedule for zone '{zone_name_raw}': {e}")
            last_schedule_refresh = now

        # Publiceren van huidige en toekomstige setpoints
        for z in zones:
            zone_name_raw = z["name"]
            zone_name = zone_name_raw.lower().replace(" ", "_")
            schedule = schedules_per_zone.get(zone_name, [])

            set_now = compute_future_setpoint(schedule, now)
            t30 = compute_future_setpoint(schedule, now + timedelta(minutes=30)) or set_now
            t60 = compute_future_setpoint(schedule, now + timedelta(minutes=60)) or set_now

            base_state_topic = f"{base_topic}/zone/{zone_name}"
            mqttc.publish(f"{base_state_topic}/setpoint_now/state", f"{set_now:.1f}", retain=True)
            mqttc.publish(f"{base_state_topic}/setpoint_30m/state", f"{t30:.1f}", retain=True)
            mqttc.publish(f"{base_state_topic}/setpoint_60m/state", f"{t60:.1f}", retain=True)

            logger.info(f"Zone {zone_name_raw}: now={set_now} +30m={t30} +60m={t60}")

        time_module.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", default="config.yml")
    args = parser.parse_args()
    export_loop(args.config)
