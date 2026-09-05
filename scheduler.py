import os
import sys
import json
import time
import uuid
import socket
import logging
import argparse
from datetime import datetime, timedelta
import pytz
import requests
import urllib3.util.connection as urllib3_conn
from dotenv import load_dotenv

load_dotenv()

# Force IPv4 resolution to avoid potential network routing issues
def allowed_gai_family():
    return socket.AF_INET

urllib3_conn.allowed_gai_family = allowed_gai_family

# --- Configuration ---

BASE_URL = "https://portal.ufsm.br/mobile/webservice"
TIMEZONE = pytz.timezone("America/Sao_Paulo")

APP_NAME = "UFSMDigital"
DEVICE_INFO = "Android generic android:11"
USER_AGENT = "Dart/3.0 (dart:io)"

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Connection": "keep-alive",
}

RESTAURANT_IDS = {
    1: 1,   # RU Campus I
    2: 41,  # RU Campus II
}

MEAL_TYPES = {
    "coffee": "CAFE",
    "lunch": "ALMOCO",
    "dinner": "JANTAR",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def resolve_config_path(path: str = "config.json") -> str:
    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        return env_path
    if path != "config.json":
        return path
    if os.path.exists("data"):
        return os.path.join("data", "config.json")
    return "config.json"


def load_config(path: str = "config.json") -> dict:
    resolved = resolve_config_path(path)
    if not os.path.exists(resolved):
        # Fallback to local config.json if data/config.json is not yet created
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    with open(resolved, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict, path: str = "config.json") -> None:
    resolved = resolve_config_path(path)
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_or_generate_device_id(config: dict, config_path: str = "config.json") -> str:
    device_id = config.get("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
        config["device_id"] = device_id
        try:
            save_config(config, config_path)
        except Exception:
            pass
        logger.info("Generated new device_id: %s", device_id)
    return device_id


def get_credentials(config: dict) -> tuple[str | None, str | None]:
    username = (
        os.environ.get("UFSM_USERNAME")
        or config.get("credentials", {}).get("username")
        or config.get("username")
    )
    password = (
        os.environ.get("UFSM_PASSWORD")
        or config.get("credentials", {}).get("password")
        or config.get("password")
    )
    return username, password


def login(username: str, password: str, device_id: str) -> str:
    logger.info("Authenticating as %s...", username)

    headers = {
        **HTTP_HEADERS,
        "appName": APP_NAME,
        "deviceId": device_id,
    }

    response = requests.post(
        f"{BASE_URL}/generateToken",
        json={
            "appName": APP_NAME,
            "deviceId": device_id,
            "deviceInfo": DEVICE_INFO,
            "messageToken": "",
            "login": username,
            "senha": password,
        },
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    if data.get("error"):
        raise RuntimeError(f"Login failed: {data.get('mensagem', 'unknown error')}")

    token = data.get("token")
    if not token:
        raise RuntimeError("No token returned from API despite no error flag.")

    logger.info("Authentication successful.")
    return token


def get_scheduled_meals(token: str) -> list:
    headers = {
        **HTTP_HEADERS,
        "Authorization": f"Bearer {token}",
    }
    response = requests.get(
        f"{BASE_URL}/ru/agendamentos",
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def schedule_meals_for_date_and_items(
    token: str,
    target_date: datetime,
    preferred_restaurant: int,
    is_veg: bool,
    meals_to_schedule: list[str],
    device_id: str,
) -> None:
    if not meals_to_schedule:
        return

    date_str = target_date.strftime("%Y-%m-%d")
    restaurant_meal_map = {}

    for meal in meals_to_schedule:
        if meal == "lunch":
            target_rest_id = RESTAURANT_IDS.get(preferred_restaurant, preferred_restaurant)
            restaurant_meal_map.setdefault(target_rest_id, []).append(MEAL_TYPES["lunch"])
        elif meal == "coffee":
            restaurant_meal_map.setdefault(RESTAURANT_IDS[1], []).append(MEAL_TYPES["coffee"])
        elif meal == "dinner":
            restaurant_meal_map.setdefault(RESTAURANT_IDS[1], []).append(MEAL_TYPES["dinner"])

    for rest_id, api_meals in restaurant_meal_map.items():
        rest_name = "RU II (Campus II)" if rest_id == RESTAURANT_IDS[2] else "RU I (Campus I)"
        logger.info(
            "Scheduling for %s at %s: %s (vegetarian=%s)",
            date_str,
            rest_name,
            ", ".join(api_meals),
            is_veg,
        )

        payload = {
            "dataInicio": f"{date_str} 00:00:00",
            "dataFim": f"{date_str} 23:59:59",
            "idRestaurante": rest_id,
            "opcaoVegetariana": is_veg,
            "tiposRefeicoes": api_meals,
        }

        headers = {
            **HTTP_HEADERS,
            "Authorization": f"Bearer {token}",
            "appName": APP_NAME,
            "deviceId": device_id,
        }

        response = requests.post(
            f"{BASE_URL}/ru/agendarRefeicao",
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        if data.get("error"):
            raise RuntimeError(
                f"Scheduling failed for {date_str} at {rest_name}: {data.get('mensagem', 'unknown error')}"
            )

        logger.info("Successfully scheduled %s at %s for %s.", ", ".join(api_meals), rest_name, date_str)


def find_schedule_for_weekday(schedules: list, weekday_abbr: str) -> dict | None:
    for entry in schedules:
        if entry.get("weekday") == weekday_abbr:
            return entry
    return None


def run_single_cycle(config_path: str = "config.json", meal_filter: str | None = None) -> None:
    config = load_config(config_path)
    schedules = config.get("schedules", [])
    if not schedules:
        logger.warning("No schedules defined in %s. Nothing to do.", config_path)
        return

    username, password = get_credentials(config)
    if not username or not password:
        logger.error("Missing UFSM credentials. Set them in config.json or via UFSM_USERNAME/UFSM_PASSWORD.")
        return

    device_id = get_or_generate_device_id(config, config_path)
    token = login(username, password, device_id)

    now = datetime.now(TIMEZONE)
    today = now
    tomorrow = now + timedelta(days=1)

    # Coffee: booked 1 day ahead (cutoff ~13h previous day)
    # Lunch: booked 1 day ahead (cutoff ~22h previous day)
    # Dinner: booked same day (cutoff ~11h30 same day)
    plan = {
        "tomorrow": {
            "date": tomorrow,
            "weekday": tomorrow.strftime("%a"),
            "meals": ["coffee", "lunch"],
        },
        "today": {
            "date": today,
            "weekday": today.strftime("%a"),
            "meals": ["dinner"],
        },
    }

    if meal_filter:
        if meal_filter in ["coffee", "lunch"]:
            plan["tomorrow"]["meals"] = [meal_filter]
            plan["today"]["meals"] = []
        elif meal_filter == "dinner":
            plan["tomorrow"]["meals"] = []
            plan["today"]["meals"] = ["dinner"]

    for bucket in plan.values():
        target_date = bucket["date"]
        weekday = bucket["weekday"]
        allowed_meals = bucket["meals"]
        if not allowed_meals:
            continue

        schedule_entry = find_schedule_for_weekday(schedules, weekday)
        if not schedule_entry:
            logger.info("No schedule configured for %s (%s). Skipping.", weekday, target_date.strftime("%Y-%m-%d"))
            continue

        meals_to_schedule = [
            meal for meal in allowed_meals if schedule_entry.get(meal) is True
        ]
        if not meals_to_schedule:
            continue

        preferred_rest = schedule_entry.get("restaurant", 1)
        is_veg = schedule_entry.get("vegetarian", False)

        try:
            schedule_meals_for_date_and_items(
                token=token,
                target_date=target_date,
                preferred_restaurant=preferred_rest,
                is_veg=is_veg,
                meals_to_schedule=meals_to_schedule,
                device_id=device_id,
            )
        except Exception as err:
            logger.error("Failed scheduling for %s (%s): %s", weekday, target_date.strftime("%Y-%m-%d"), err)


def run_daemon_loop(config_path: str = "config.json") -> None:
    logger.info("RU Bot daemon started. Running in continuous mode (America/Sao_Paulo).")
    # Target execution windows:
    # 11:30 -> Dinner (same day)
    # 13:00 -> Coffee (next day)
    # 22:00 -> Lunch (next day)
    last_triggered = {}

    while True:
        try:
            now = datetime.now(TIMEZONE)
            current_day = now.strftime("%Y-%m-%d")
            hour = now.hour
            minute = now.minute

            # Dinner trigger window: 11:30 - 11:35
            if (hour == 11 and 30 <= minute <= 35) and last_triggered.get((current_day, "dinner")) is None:
                logger.info("Triggering scheduled check: Dinner (today)")
                run_single_cycle(config_path, meal_filter="dinner")
                last_triggered[(current_day, "dinner")] = True

            # Coffee trigger window: 13:00 - 13:05
            if (hour == 13 and 0 <= minute <= 5) and last_triggered.get((current_day, "coffee")) is None:
                logger.info("Triggering scheduled check: Coffee (tomorrow)")
                run_single_cycle(config_path, meal_filter="coffee")
                last_triggered[(current_day, "coffee")] = True

            # Lunch trigger window: 22:00 - 22:05
            if (hour == 22 and 0 <= minute <= 5) and last_triggered.get((current_day, "lunch")) is None:
                logger.info("Triggering scheduled check: Lunch (tomorrow)")
                run_single_cycle(config_path, meal_filter="lunch")
                last_triggered[(current_day, "lunch")] = True

            # Housekeeping old trigger keys
            if len(last_triggered) > 20:
                last_triggered = {k: v for k, v in last_triggered.items() if k[0] == current_day}

        except Exception as err:
            logger.error("Unexpected error in daemon loop: %s", err)

        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="RU Bot Scheduler")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scheduling check immediately and exit (default is daemon loop)",
    )
    parser.add_argument(
        "--meal",
        choices=["coffee", "lunch", "dinner"],
        default=None,
        help="Filter specific meal when running with --once",
    )
    args = parser.parse_args()

    if args.once:
        logger.info("Running in one-shot mode.")
        run_single_cycle(args.config, meal_filter=args.meal)
    else:
        run_daemon_loop(args.config)


if __name__ == "__main__":
    main()
