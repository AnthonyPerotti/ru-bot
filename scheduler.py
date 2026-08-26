import sys
import json
import uuid
import socket
import logging
import requests
from datetime import datetime, timedelta
import pytz
import urllib3.util.connection as urllib3_conn

# Force IPv4 resolution to prevent [Errno 101] Network unreachable on GitHub Actions runners
def allowed_gai_family():
    return socket.AF_INET

urllib3_conn.allowed_gai_family = allowed_gai_family

# --- Configuration ---

BASE_URL = "https://portal.ufsm.br/mobile/webservice"
TIMEZONE = pytz.timezone("America/Sao_Paulo")

# Device and client headers simulating official UFSMDigital mobile app
APP_NAME = "UFSMDigital"
DEVICE_INFO = "Android generic android:11"
USER_AGENT = "Dart/3.0 (dart:io)"

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Connection": "keep-alive",
}

# Restaurant ID mapping (from portal source)
RESTAURANT_IDS = {
    1: 1,   # RU Campus I
    2: 41,  # RU Campus II
}


# Meal type codes used by the API
MEAL_TYPES = {
    "coffee": "CAFE",
    "lunch": "ALMOCO",
    "dinner": "JANTAR",
}

# Deadline offsets (hours before the meal window opens)
# Used to determine which meals are still schedulable today
MEAL_DEADLINES = {
    # Coffee: must schedule by 13h the day before
    "coffee": {"offset_days": 1, "cutoff_hour": 13},
    # Lunch: must schedule by 22h the day before
    "lunch": {"offset_days": 1, "cutoff_hour": 22},
    # Dinner: must schedule by 11h30 of the same day
    "dinner": {"offset_days": 0, "cutoff_hour": 11, "cutoff_minute": 30},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_or_generate_device_id(config: dict) -> str:
    """Returns existing device-id from config or generates a new one."""
    device_id = config.get("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
        logger.warning("No device_id found in config. Generated: %s", device_id)
    return device_id


def login(username: str, password: str, device_id: str) -> str:
    """Authenticates against the UFSM mobile API and returns a session token."""
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
    """Fetches the list of already scheduled meals to avoid duplicates."""
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


def schedule_meal(token: str, target_date: datetime, schedule: dict, device_id: str) -> None:
    """Schedules meals for a given date based on the schedule config entry."""
    preferred_restaurant = schedule.get("restaurant", 1)
    is_veg = schedule.get("vegetarian", False)
    date_str = target_date.strftime("%Y-%m-%d")

    # Map requested meals to their respective restaurant.
    # Note on UFSM RU rules:
    # RU II (Campus II) only serves Lunch (ALMOCO).
    # Breakfast (CAFE) and Dinner (JANTAR) are served at RU I (Campus I).
    # If the user chooses RU II as preferred, Lunch goes to RU II and Breakfast/Dinner go to RU I.
    restaurant_meal_map = {}

    if schedule.get("coffee"):
        # Breakfast is always at RU I
        restaurant_meal_map.setdefault(RESTAURANT_IDS[1], []).append(MEAL_TYPES["coffee"])

    if schedule.get("lunch"):
        # Lunch goes to user's preferred restaurant (RU I or RU II)
        target_rest_id = RESTAURANT_IDS.get(preferred_restaurant, preferred_restaurant)
        restaurant_meal_map.setdefault(target_rest_id, []).append(MEAL_TYPES["lunch"])

    if schedule.get("dinner"):
        # Dinner is always at RU I
        restaurant_meal_map.setdefault(RESTAURANT_IDS[1], []).append(MEAL_TYPES["dinner"])

    if not restaurant_meal_map:
        logger.info("No meals configured for %s. Skipping.", target_date.strftime("%a %Y-%m-%d"))
        return

    for rest_id, meals in restaurant_meal_map.items():
        rest_name = "RU II (Campus II)" if rest_id == RESTAURANT_IDS[2] else "RU I (Campus I)"
        logger.info(
            "Scheduling for %s at %s: %s (vegetarian=%s)",
            date_str,
            rest_name,
            ", ".join(meals),
            is_veg,
        )

        payload = {
            "dataInicio": f"{date_str} 00:00:00",
            "dataFim": f"{date_str} 23:59:59",
            "idRestaurante": rest_id,
            "opcaoVegetariana": is_veg,
            "tiposRefeicoes": meals,
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

        logger.info("Successfully scheduled %s at %s for %s.", ", ".join(meals), rest_name, date_str)


def find_schedule_for_weekday(schedules: list, weekday_abbr: str) -> dict | None:
    """Finds the schedule entry matching the given weekday abbreviation (Mon, Tue, etc.)."""
    for entry in schedules:
        if entry.get("weekday") == weekday_abbr:
            return entry
    return None


def run(username: str, password: str, config_path: str = "config.json") -> None:
    config = load_config(config_path)
    device_id = get_or_generate_device_id(config)
    schedules = config.get("schedules", [])

    if not schedules:
        logger.warning("No schedules defined in config. Nothing to do.")
        return

    token = login(username, password, device_id)

    # We target the next calendar day by default (run at ~23h BRT)
    now = datetime.now(TIMEZONE)
    target_date = now + timedelta(days=1)
    weekday_abbr = target_date.strftime("%a")  # "Mon", "Tue", etc.

    logger.info(
        "Current time: %s | Targeting: %s (%s)",
        now.strftime("%Y-%m-%d %H:%M %Z"),
        target_date.strftime("%Y-%m-%d"),
        weekday_abbr,
    )

    schedule_entry = find_schedule_for_weekday(schedules, weekday_abbr)
    if not schedule_entry:
        logger.info("No schedule configured for %s. Skipping.", weekday_abbr)
        return

    schedule_meal(token, target_date, schedule_entry, device_id)


if __name__ == "__main__":
    import os

    username = os.environ.get("UFSM_USERNAME")
    password = os.environ.get("UFSM_PASSWORD")

    if not username or not password:
        logger.error("UFSM_USERNAME and UFSM_PASSWORD environment variables must be set.")
        sys.exit(1)

    try:
        run(username, password)
    except Exception as exc:
        logger.exception("Scheduler failed: %s", exc)
        sys.exit(1)
