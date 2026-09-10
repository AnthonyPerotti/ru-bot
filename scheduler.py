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

# Import the web-based scheduler (uses OCR instead of broken mobile API)
try:
    from web_scheduler import run_web_schedule
    WEB_SCHEDULER_AVAILABLE = True
except ImportError:
    WEB_SCHEDULER_AVAILABLE = False

_prefer_ipv6 = None

def allowed_gai_family():
    global _prefer_ipv6
    if _prefer_ipv6 is None:
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s.settimeout(1.5)
            s.connect(("2804:0:4000:4::123", 443))
            s.close()
            _prefer_ipv6 = True
        except Exception:
            _prefer_ipv6 = False
    return socket.AF_INET6 if _prefer_ipv6 else socket.AF_INET

urllib3_conn.allowed_gai_family = allowed_gai_family

# --- Configuration ---

BASE_URL = "https://portal.ufsm.br/mobile/webservice"  # legacy mobile API (mostly broken)
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


# Internal meal code mapping: config key -> portal API code
_MEAL_CODE_MAP = {
    "coffee": "CAFE",
    "lunch": "ALMOCO",
    "dinner": "JANTAR",
}


def run_single_cycle(config_path: str = "config.json", meal_filter: str | None = None) -> None:
    """
    One-shot scheduling run. Used by --once CLI mode.
    Delegates to _run_single_cycle_tracked so that retry logic, routing,
    and logging are identical to what the daemon uses.
    """
    _run_single_cycle_tracked(config_path, meal_filter=meal_filter or "")


def _run_single_cycle_tracked(config_path: str, meal_filter: str) -> bool:
    """
    Wrapper around run_single_cycle that returns True if all meals were
    successfully scheduled, False if any failure occurred.
    """
    config = load_config(config_path)
    schedules = config.get("schedules", [])
    if not schedules:
        return True  # nothing to do is not a failure

    username, password = get_credentials(config)
    if not username or not password:
        logger.error("Missing UFSM credentials.")
        return False

    if not WEB_SCHEDULER_AVAILABLE:
        logger.error("web_scheduler module not available.")
        return False

    now = datetime.now(TIMEZONE)
    today = now
    tomorrow = now + timedelta(days=1)

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

    if meal_filter in ["coffee", "lunch"]:
        plan["tomorrow"]["meals"] = [meal_filter]
        plan["today"]["meals"] = []
    elif meal_filter == "dinner":
        plan["tomorrow"]["meals"] = []
        plan["today"]["meals"] = ["dinner"]

    all_ok = True

    for bucket in plan.values():
        target_date = bucket["date"]
        weekday = bucket["weekday"]
        allowed_meals = bucket["meals"]
        if not allowed_meals:
            continue

        schedule_entry = find_schedule_for_weekday(schedules, weekday)
        if not schedule_entry:
            continue

        meals_to_schedule = [m for m in allowed_meals if schedule_entry.get(m) is True]
        if not meals_to_schedule:
            continue

        preferred_rest = schedule_entry.get("restaurant", 1)
        is_veg = schedule_entry.get("vegetarian", False)

        restaurant_meal_groups: dict[int, list[str]] = {}
        for meal in meals_to_schedule:
            code = _MEAL_CODE_MAP.get(meal)
            if not code:
                continue
            if meal in ["coffee", "dinner"] and preferred_rest == 2:
                restaurant_meal_groups.setdefault(1, []).append(code)
            else:
                restaurant_meal_groups.setdefault(preferred_rest, []).append(code)

        for target_rest, meal_codes in restaurant_meal_groups.items():
            rest_label = "RU II (Campus II)" if target_rest == 2 else "RU I (Campus I)"

            _MAX_INNER_ATTEMPTS = 3
            _INNER_RETRY_DELAY = 60  # seconds between internal retries

            group_ok = False
            for inner_attempt in range(1, _MAX_INNER_ATTEMPTS + 1):
                try:
                    results = run_web_schedule(
                        username=username,
                        password=password,
                        target_date=target_date,
                        restaurant_id=target_rest,
                        is_veg=is_veg,
                        meals=meal_codes,
                    )
                    attempt_ok = True
                    for meal_code, success in results.items():
                        if success:
                            logger.info(
                                "[OK] %s on %s at %s (attempt %d/%d).",
                                meal_code, target_date.strftime("%Y-%m-%d"),
                                rest_label, inner_attempt, _MAX_INNER_ATTEMPTS,
                            )
                        else:
                            logger.error(
                                "[FAIL] %s on %s at %s (attempt %d/%d).",
                                meal_code, target_date.strftime("%Y-%m-%d"),
                                rest_label, inner_attempt, _MAX_INNER_ATTEMPTS,
                            )
                            attempt_ok = False

                    if attempt_ok:
                        group_ok = True
                        break  # success — no need to retry

                except Exception as err:
                    logger.error(
                        "Error scheduling %s at %s (attempt %d/%d): %s",
                        meal_codes, rest_label, inner_attempt, _MAX_INNER_ATTEMPTS, err,
                    )

                # If there are more attempts left, wait before retrying
                if inner_attempt < _MAX_INNER_ATTEMPTS:
                    logger.warning(
                        "Waiting %ds before retry %d/%d for %s at %s...",
                        _INNER_RETRY_DELAY, inner_attempt + 1, _MAX_INNER_ATTEMPTS,
                        meal_codes, rest_label,
                    )
                    time.sleep(_INNER_RETRY_DELAY)

            if not group_ok:
                all_ok = False

    return all_ok



def _get_trigger_path(config_path: str) -> str:
    """Returns the path of the .schedule_trigger sentinel file."""
    resolved = resolve_config_path(config_path)
    return os.path.join(os.path.dirname(os.path.abspath(resolved)), ".schedule_trigger")


def _check_and_consume_trigger(config_path: str) -> bool:
    """Returns True (and deletes the file) if a trigger file exists."""
    path = _get_trigger_path(config_path)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
        return True
    return False


def run_daemon_loop(config_path: str = "config.json") -> None:
    """
    Continuous scheduling daemon.

    Each meal has a hard deadline imposed by the UFSM portal:
      - Dinner  -> 11:30 (same day)
      - Coffee  -> 13:00 (next day)
      - Lunch   -> 22:00 (next day)

    Attempt 1 runs 2 hours before the deadline.
    If attempt 1 fails (server error, captcha failure, etc.) the state is
    recorded as "failed" and attempt 2 runs 30 minutes before the deadline.
    A successful attempt (in either window) marks the meal as "ok" for that day.
    """
    logger.info("RU Bot daemon started. Running in continuous mode (America/Sao_Paulo).")

    # Values: None (not attempted), "failed" (attempt 1 failed), "ok" (done)
    status: dict[tuple, str] = {}

    # Each entry: (meal, fa_h, fa_m_start, fa_m_end, rt_h, rt_m_start, rt_m_end)
    # fa = first attempt (2h before deadline), rt = retry (30min before deadline)
    WINDOWS = [
        # Dinner: deadline 11:30 -> first at 09:30-09:35, retry at 11:00-11:05
        ("dinner", 9, 30, 35, 11, 0, 5),
        # Coffee: deadline 13:00 -> first at 11:00-11:05, retry at 12:30-12:35
        ("coffee", 11, 0, 5, 12, 30, 35),
        # Lunch: deadline 22:00 -> first at 20:00-20:05, retry at 21:30-21:35
        ("lunch", 20, 0, 5, 21, 30, 35),
    ]

    while True:
        try:
            now = datetime.now(TIMEZONE)
            current_day = now.strftime("%Y-%m-%d")
            h = now.hour
            m = now.minute

            # --- Normal scheduling windows ---
            for meal, fa_h, fa_m_start, fa_m_end, rt_h, rt_m_start, rt_m_end in WINDOWS:
                key = (current_day, meal)
                current_status = status.get(key)

                # First attempt window (2h before deadline)
                in_first_window = (h == fa_h and fa_m_start <= m <= fa_m_end)
                # Retry window (30min before deadline)
                in_retry_window = (h == rt_h and rt_m_start <= m <= rt_m_end)

                if in_first_window and current_status is None:
                    logger.info("Attempt 1/2 — scheduling: %s", meal)
                    ok = _run_single_cycle_tracked(config_path, meal_filter=meal)
                    status[key] = "ok" if ok else "failed"
                    if not ok:
                        logger.warning(
                            "Attempt 1 failed for %s. Retry scheduled in the next window.", meal
                        )

                elif in_retry_window and current_status == "failed":
                    logger.warning("Attempt 2/2 (retry) — scheduling: %s", meal)
                    ok = _run_single_cycle_tracked(config_path, meal_filter=meal)
                    status[key] = "ok" if ok else "failed"
                    if ok:
                        logger.info("Retry succeeded for %s.", meal)
                    else:
                        logger.error(
                            "Retry also failed for %s. No more attempts will be made today.", meal
                        )

            # --- Trigger file: user saved config via web UI ---
            # If the save happened after the normal window, schedule immediately
            # for any meal that is still within its portal deadline.
            if _check_and_consume_trigger(config_path):
                logger.info("Config save detected — checking for missed scheduling windows.")
                current_minutes = h * 60 + m
                for meal, fa_h, fa_m_start, fa_m_end, rt_h, rt_m_start, rt_m_end in WINDOWS:
                    key = (current_day, meal)
                    if status.get(key) == "ok":
                        continue  # already done today

                    # Deadline (hard limit) for each meal in minutes since midnight:
                    #   dinner -> 11:30, coffee -> 13:00, lunch -> 22:00
                    deadline_map = {"dinner": 11 * 60 + 30, "coffee": 13 * 60, "lunch": 22 * 60}
                    deadline_minutes = deadline_map[meal]

                    # The first-attempt window start in minutes
                    first_window_start = fa_h * 60 + fa_m_start

                    # Act if we are past the first window start AND still before the deadline
                    if current_minutes >= first_window_start and current_minutes < deadline_minutes:
                        logger.warning(
                            "Trigger: past normal window for %s — running immediate attempt "
                            "(%.0f min before deadline).",
                            meal,
                            deadline_minutes - current_minutes,
                        )
                        ok = _run_single_cycle_tracked(config_path, meal_filter=meal)
                        status[key] = "ok" if ok else "failed"
                        if ok:
                            logger.info("Trigger attempt succeeded for %s.", meal)
                        else:
                            logger.error(
                                "Trigger attempt failed for %s. "
                                "Will retry in the next normal window if still within deadline.",
                                meal,
                            )

            # Housekeeping: discard state older than today
            if len(status) > 30:
                status = {k: v for k, v in status.items() if k[0] == current_day}

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
