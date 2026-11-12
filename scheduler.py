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

# Fallback web scheduler (if installed/available)
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
# Official UFSM Digital Flutter Mobile API (instant, no captcha required)
BASE_URL = "https://portal.ufsm.br/mobile/webservice/flutter"
TIMEZONE = pytz.timezone("America/Sao_Paulo")

APP_NAME = "UFSMDigital"
DEVICE_INFO = "Apple iPhone ios:15.7.3"
DEFAULT_MESSAGE_TOKEN = (
    "c7ptbA7De0nvnvagiGEgbC:APA91bE1AABlRKEjUB_HCB_yVKmocYxOgym2ebWlpP6hCjMYpTcgiTMiK"
    "Tu7KZgTMLIrv55SieM0fLqWBIiMLULrwTDISoszte9zMAVaMfQqt9cxAHaxJ47moYT628v9JMBQftaLVxKm"
)

HTTP_HEADERS = {
    "User-Agent": "Dart/3.12 (dart:io)",
    "x-ufsm-version": "50600",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json; charset=UTF-8",
}

# Restaurant mappings:
# 1 -> RU Campus I
# 2 / 41 -> RU Campus II
RESTAURANT_IDS = {
    1: 1,
    2: 41,
    41: 41,
}

# Meal integer IDs used by the Flutter mobile API:
# 1: Café da manhã
# 2: Almoço
# 3: Jantar
MEAL_ID_MAP = {
    "coffee": 1,
    "lunch": 2,
    "dinner": 3,
}

MEAL_NAMES = {
    1: "CAFE",
    2: "ALMOCO",
    3: "JANTAR",
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
    """Authenticates against the official UFSM Digital mobile API via JWT."""
    logger.info("Authenticating via UFSM mobile API as %s...", username)

    payload = {
        "appName": APP_NAME,
        "deviceId": device_id,
        "deviceInfo": DEVICE_INFO,
        "messageToken": DEFAULT_MESSAGE_TOKEN,
        "login": username,
        "senha": password,
    }

    response = requests.post(
        f"{BASE_URL}/generateTokenJwt",
        json=payload,
        headers=HTTP_HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    if data.get("error"):
        error_msg = data.get("mensagem") or data.get("body") or "Unknown error"
        raise RuntimeError(f"Login failed: {error_msg}")

    body = data.get("body")
    if not isinstance(body, dict) or not body.get("accessToken"):
        raise RuntimeError(f"No access token returned: {data}")

    token = body["accessToken"]
    logger.info("Authentication successful.")
    return token


def schedule_meals_api(
    token: str,
    target_date: datetime,
    restaurant_id: int,
    is_veg: bool,
    meal_ids: list[int],
    device_id: str,
) -> tuple[bool, str]:
    """
    Directly reserves meals through the UFSM Digital mobile API.
    Bypasses web scraping and captchas completely.
    """
    if not meal_ids:
        return True, "No meals requested"

    date_str = target_date.strftime("%Y-%m-%d")
    rest_id = 41 if restaurant_id in [2, 41] else 1

    payload = {
        "dataInicio": f"{date_str} 00:00:00",
        "dataFim": f"{date_str} 00:00:00",
        "idRestaurante": rest_id,
        "opcaoVegetariana": is_veg,
        "tiposRefeicoes": meal_ids,
    }

    headers = {
        **HTTP_HEADERS,
        "X-UFSM-Device-ID": device_id,
        "Authorization": f"Bearer {token}",
    }

    response = requests.post(
        f"{BASE_URL}/ru/agendaRefeicoes",
        json=payload,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    if data.get("error"):
        error_msg = data.get("mensagem") or data.get("body") or "Unknown API error"
        return False, str(error_msg)

    body = data.get("body", [])
    if isinstance(body, dict):
        body = [body]

    all_success = True
    messages = []

    for item in body:
        meal_name = item.get("tipoRefeicao") or "Refeição"
        is_ok = bool(item.get("sucesso"))
        impedimento = item.get("impedimento") or ""

        # Treat already scheduled as success
        lower_imp = impedimento.lower()
        if is_ok or "já possui" in lower_imp or "já existe" in lower_imp:
            status_desc = "Agendado com sucesso" if is_ok else impedimento
            messages.append(f"{meal_name}: OK ({status_desc})")
        else:
            all_success = False
            messages.append(f"{meal_name}: FALHA ({impedimento})")

    return all_success, " | ".join(messages) if messages else "Processado"


def find_schedule_for_weekday(schedules: list, weekday_abbr: str) -> dict | None:
    for entry in schedules:
        if entry.get("weekday") == weekday_abbr:
            return entry
    return None


def run_single_cycle(config_path: str = "config.json", meal_filter: str | None = None) -> None:
    _run_single_cycle_tracked(config_path, meal_filter=meal_filter or "")


def _run_single_cycle_tracked(config_path: str, meal_filter: str) -> bool:
    """Executes a single pass over pending meals using the mobile API."""
    config = load_config(config_path)
    schedules = config.get("schedules", [])
    if not schedules:
        return True

    username, password = get_credentials(config)
    if not username or not password:
        logger.error("Missing UFSM credentials in config or environment.")
        return False

    device_id = get_or_generate_device_id(config, config_path)

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

    # Authenticate via mobile API
    try:
        token = login(username, password, device_id)
    except Exception as err:
        logger.error("Failed to authenticate with UFSM mobile API: %s", err)
        return False

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

        # RU II (Campus II) only serves lunch.
        # Direct coffee and dinner to RU I (Campus I).
        restaurant_meal_groups: dict[int, list[tuple[str, int]]] = {}
        for meal in meals_to_schedule:
            meal_id = MEAL_ID_MAP.get(meal)
            if not meal_id:
                continue
            if meal in ["coffee", "dinner"] and preferred_rest in [2, 41]:
                restaurant_meal_groups.setdefault(1, []).append((meal, meal_id))
            else:
                target_r = 41 if preferred_rest in [2, 41] else 1
                restaurant_meal_groups.setdefault(target_r, []).append((meal, meal_id))

        for target_rest, meal_pairs in restaurant_meal_groups.items():
            rest_label = "RU II (Campus II)" if target_rest == 41 else "RU I (Campus I)"
            meal_names = [p[0] for p in meal_pairs]
            meal_ids = [p[1] for p in meal_pairs]
            date_str = target_date.strftime("%Y-%m-%d")

            try:
                ok, details = schedule_meals_api(
                    token=token,
                    target_date=target_date,
                    restaurant_id=target_rest,
                    is_veg=is_veg,
                    meal_ids=meal_ids,
                    device_id=device_id,
                )

                if ok:
                    logger.info(
                        "[OK] %s on %s at %s: %s",
                        ", ".join(meal_names),
                        date_str,
                        rest_label,
                        details,
                    )
                else:
                    logger.error(
                        "[FAIL] %s on %s at %s: %s",
                        ", ".join(meal_names),
                        date_str,
                        rest_label,
                        details,
                    )
                    all_ok = False
            except Exception as err:
                logger.error(
                    "Error scheduling %s on %s at %s: %s",
                    ", ".join(meal_names),
                    date_str,
                    rest_label,
                    err,
                )
                all_ok = False

    return all_ok


def _get_trigger_path(config_path: str) -> str:
    resolved = resolve_config_path(config_path)
    return os.path.join(os.path.dirname(os.path.abspath(resolved)), ".schedule_trigger")


def _check_and_consume_trigger(config_path: str) -> bool:
    path = _get_trigger_path(config_path)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
        return True
    return False


# Scheduling rules per meal type:
# - start: (hour, minute) when initial attempts start (~12h before deadline)
# - deadline: (hour, minute) official deadline enforced by UFSM portal
# - max_attempts: maximum number of retries before deadline
# - retry_interval_minutes: interval in minutes between retries on network/server failure
MEAL_RULES = {
    "dinner": {
        "start": (0, 0),
        "deadline": (11, 30),
        "max_attempts": 50,
        "retry_interval_minutes": 15,
    },
    "coffee": {
        "start": (1, 0),
        "deadline": (13, 0),
        "max_attempts": 50,
        "retry_interval_minutes": 15,
    },
    "lunch": {
        "start": (10, 0),
        "deadline": (22, 0),
        "max_attempts": 50,
        "retry_interval_minutes": 15,
    },
}


def run_daemon_loop(config_path: str = "config.json") -> None:
    """Continuous scheduling daemon using the official mobile API."""
    logger.info("RU Bot daemon started using UFSM mobile API (America/Sao_Paulo).")

    # State per (date_str, meal): { "status": "pending"|"ok"|"failed"|"expired", "attempts": int, "last_attempt": datetime }
    status: dict[tuple[str, str], dict] = {}

    while True:
        try:
            now = datetime.now(TIMEZONE)
            current_day = now.strftime("%Y-%m-%d")
            current_minutes = now.hour * 60 + now.minute

            # --- Check each meal schedule ---
            for meal, rule in MEAL_RULES.items():
                key = (current_day, meal)
                meal_state = status.setdefault(
                    key,
                    {
                        "status": "pending",
                        "attempts": 0,
                        "last_attempt": None,
                    },
                )

                if meal_state["status"] == "ok":
                    continue

                start_minutes = rule["start"][0] * 60 + rule["start"][1]
                deadline_minutes = rule["deadline"][0] * 60 + rule["deadline"][1]
                max_attempts = rule["max_attempts"]
                retry_interval = rule["retry_interval_minutes"]

                if current_minutes >= deadline_minutes:
                    if meal_state["status"] != "expired":
                        meal_state["status"] = "expired"
                        logger.warning(
                            "Deadline reached for %s (%02d:%02d). No further attempts today.",
                            meal,
                            rule["deadline"][0],
                            rule["deadline"][1],
                        )
                    continue

                if current_minutes < start_minutes:
                    continue

                if meal_state["attempts"] >= max_attempts:
                    continue

                should_run = False
                if meal_state["attempts"] == 0:
                    should_run = True
                else:
                    last_attempt = meal_state["last_attempt"]
                    if last_attempt is not None:
                        elapsed = (now - last_attempt).total_seconds() / 60
                        minutes_to_deadline = deadline_minutes - current_minutes
                        if elapsed >= retry_interval or (minutes_to_deadline <= 20 and elapsed >= 10):
                            should_run = True

                if should_run:
                    attempt_num = meal_state["attempts"] + 1
                    is_retry = meal_state["attempts"] > 0
                    retry_label = " (retry)" if is_retry else ""

                    logger.info(
                        "Attempt %d/%d%s — scheduling: %s (deadline: %02d:%02d)",
                        attempt_num,
                        max_attempts,
                        retry_label,
                        meal,
                        rule["deadline"][0],
                        rule["deadline"][1],
                    )

                    ok = _run_single_cycle_tracked(config_path, meal_filter=meal)
                    meal_state["attempts"] = attempt_num
                    meal_state["last_attempt"] = now

                    if ok:
                        meal_state["status"] = "ok"
                        logger.info("Attempt %d/%d succeeded for %s.", attempt_num, max_attempts, meal)
                    else:
                        meal_state["status"] = "failed"
                        remaining = max_attempts - attempt_num
                        if remaining > 0 and (deadline_minutes - current_minutes > 25):
                            logger.warning(
                                "Attempt %d/%d failed for %s. Next retry in ~%d minutes (deadline is %02d:%02d).",
                                attempt_num,
                                max_attempts,
                                meal,
                                retry_interval,
                                rule["deadline"][0],
                                rule["deadline"][1],
                            )
                        else:
                            logger.error(
                                "Retry attempts exhausted for %s today (%d/%d attempts).",
                                meal,
                                attempt_num,
                                max_attempts,
                            )

            # --- Trigger file: user saved config via web UI ---
            if _check_and_consume_trigger(config_path):
                logger.info("Config save detected — checking for pending meals within deadlines.")
                for meal, rule in MEAL_RULES.items():
                    key = (current_day, meal)
                    meal_state = status.setdefault(
                        key,
                        {
                            "status": "pending",
                            "attempts": 0,
                            "last_attempt": None,
                        },
                    )

                    if meal_state["status"] == "ok":
                        continue

                    start_minutes = rule["start"][0] * 60 + rule["start"][1]
                    deadline_minutes = rule["deadline"][0] * 60 + rule["deadline"][1]

                    if current_minutes >= start_minutes and current_minutes < deadline_minutes:
                        attempt_num = meal_state["attempts"] + 1
                        max_attempts = rule["max_attempts"]
                        logger.info(
                            "Trigger: running immediate attempt %d/%d for %s (%02d min before deadline)...",
                            attempt_num,
                            max_attempts,
                            meal,
                            deadline_minutes - current_minutes,
                        )
                        ok = _run_single_cycle_tracked(config_path, meal_filter=meal)
                        meal_state["attempts"] = attempt_num
                        meal_state["last_attempt"] = now

                        if ok:
                            meal_state["status"] = "ok"
                            logger.info("Trigger attempt %d/%d succeeded for %s.", attempt_num, max_attempts, meal)
                        else:
                            meal_state["status"] = "failed"
                            logger.warning(
                                "Trigger attempt %d/%d failed for %s. Will retry every %d minutes until %02d:%02d.",
                                attempt_num,
                                max_attempts,
                                meal,
                                rule["retry_interval_minutes"],
                                rule["deadline"][0],
                                rule["deadline"][1],
                            )

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
