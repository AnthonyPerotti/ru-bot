"""
Automated RU Meal Scheduling Module via Web Portal and Playwright.

Bypasses:
  1. Internal image captcha (/ru/usuario/captcha.html) using local ONNX-based ddddocr.
  2. Google reCAPTCHA v2 using audio challenge transcription via faster-whisper.

Anti-detection:
  - playwright-stealth patches (navigator.webdriver, chrome runtime, plugins, etc.)
  - Randomized human-like interaction delays and mouse movements.
"""
import io
import logging
import random
import re
import time
from datetime import datetime
from typing import Optional

from PIL import Image
import requests
import ddddocr
from faster_whisper import WhisperModel
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

BASE_URL = "https://portal.ufsm.br"
FORM_URL = f"{BASE_URL}/ru/usuario/agendamento/form.html"
LOGIN_URL = f"{BASE_URL}/ru/index.html"

# Mapping of restaurants
RESTAURANT_PORTAL_IDS = {
    1: "1",    # RU Campus I
    2: "41",   # RU Campus II
    41: "41",
}

# Mapping of meal codes to form values
MEAL_PORTAL_IDS = {
    "CAFE": "1",
    "ALMOCO": "2",
    "JANTAR": "3",
    "coffee": "1",
    "lunch": "2",
    "dinner": "3",
}

# Lazy-loaded singletons
_ocr: Optional[ddddocr.DdddOcr] = None
_whisper: Optional[WhisperModel] = None


def get_ocr() -> ddddocr.DdddOcr:
    global _ocr
    if _ocr is None:
        logger.info("Initializing ddddocr OCR model...")
        _ocr = ddddocr.DdddOcr(show_ad=False)
    return _ocr


def get_whisper() -> WhisperModel:
    global _whisper
    if _whisper is None:
        logger.info("Loading faster-whisper (tiny) speech recognition model...")
        _whisper = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _whisper


def solve_text_captcha(img_bytes: bytes) -> str:
    """Classifies a 6-character captcha image using ddddocr."""
    im = Image.open(io.BytesIO(img_bytes))
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[3])
        im = bg
    else:
        im = im.convert("RGB")

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    text = get_ocr().classification(buf.getvalue()).strip().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def _human_delay(min_s: float = 0.5, max_s: float = 2.0) -> None:
    """Random delay that mimics natural human reaction time."""
    time.sleep(random.uniform(min_s, max_s))


def _human_mouse_move(page, target_x: int, target_y: int, steps: int = 0) -> None:
    """Moves the mouse to (target_x, target_y) with slight random offset."""
    offset_x = random.randint(-5, 5)
    offset_y = random.randint(-3, 3)
    if steps == 0:
        steps = random.randint(5, 15)
    page.mouse.move(target_x + offset_x, target_y + offset_y, steps=steps)
    _human_delay(0.1, 0.3)


def _simulate_idle_activity(page) -> None:
    """Performs minor idle gestures (scroll, mouse drift) to look human."""
    action = random.choice(["scroll", "move", "none"])
    if action == "scroll":
        page.mouse.wheel(0, random.randint(-50, 80))
        _human_delay(0.3, 0.8)
    elif action == "move":
        page.mouse.move(
            random.randint(200, 800),
            random.randint(200, 600),
            steps=random.randint(3, 10),
        )
        _human_delay(0.2, 0.5)


def _is_recaptcha_checked(anchor_frame) -> bool:
    """Returns True if the reCAPTCHA checkbox shows a verified state."""
    try:
        return anchor_frame.locator(
            ".recaptcha-checkbox-checked, [aria-checked='true']"
        ).count() > 0
    except Exception:
        return False


def solve_recaptcha(page, max_retries: int = 3) -> bool:
    """Handles Google reCAPTCHA v2: 1-click pass or automated audio challenge solve.

    Strategy:
      1. Simulate human-like mouse approach to the checkbox.
      2. Click and wait with realistic timing for a 1-click pass.
      3. If challenged, attempt audio solve with disabled-button detection.
      4. If the audio button is disabled (Google blocked it), reload the
         challenge frame via the "get a new challenge" button.
    """
    anchor_frame = page.frame_locator("iframe[src*='api2/anchor']")
    recaptcha_box = anchor_frame.locator("#recaptcha-anchor")

    # Approach the checkbox with human-like mouse movement
    try:
        box = recaptcha_box.bounding_box()
        if box:
            _human_mouse_move(page, int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2))
    except Exception:
        pass

    _human_delay(0.3, 0.8)
    recaptcha_box.click()
    _human_delay(2.0, 4.0)

    # Check if 1-click pass was granted
    if _is_recaptcha_checked(anchor_frame):
        logger.info("reCAPTCHA passed immediately via 1-click!")
        return True

    # Audio challenge fallback
    bframe = page.frame_locator("iframe[src*='api2/bframe']")

    for attempt in range(1, max_retries + 1):
        try:
            audio_btn = bframe.locator("#recaptcha-audio-button")

            if audio_btn.count() == 0 or not audio_btn.is_visible():
                logger.warning("Audio challenge button not available on attempt %d", attempt)
                _human_delay(1.0, 2.0)
                continue

            # Detect if the audio button is disabled (Google blocked audio channel)
            btn_classes = audio_btn.get_attribute("class") or ""
            is_disabled = audio_btn.is_disabled() or "rc-button-disabled" in btn_classes

            if is_disabled:
                logger.warning(
                    "Audio button is disabled (bot detection triggered) on attempt %d. "
                    "Requesting a new challenge...", attempt,
                )
                # Try to get a fresh challenge by clicking the reload button
                reload_btn = bframe.locator("#recaptcha-reload-button")
                if reload_btn.count() > 0 and reload_btn.is_visible():
                    # Check if reload button is also disabled (full lockout)
                    reload_classes = reload_btn.get_attribute("class") or ""
                    reload_disabled = reload_btn.is_disabled() or "rc-button-disabled" in reload_classes
                    if reload_disabled:
                        logger.warning(
                            "Reload button is also disabled — Google has fully locked out "
                            "this session. Skipping remaining audio attempts."
                        )
                        break  # No point retrying, the entire challenge is locked

                    _human_delay(0.5, 1.5)
                    reload_btn.click(force=True)
                    _human_delay(2.0, 4.0)

                    # After reload, the audio button might be re-enabled
                    btn_classes = audio_btn.get_attribute("class") or ""
                    is_disabled = audio_btn.is_disabled() or "rc-button-disabled" in btn_classes
                    if is_disabled:
                        logger.warning("Audio button still disabled after challenge reload.")
                        _human_delay(2.0, 3.0)
                        continue
                else:
                    _human_delay(1.0, 2.0)
                    continue

            logger.info("Clicking reCAPTCHA audio challenge button (attempt %d/%d)...", attempt, max_retries)
            _simulate_idle_activity(page)
            audio_btn.click()
            _human_delay(2.0, 4.0)

            # Wait longer for the audio source to appear (increased from 5s to 10s)
            audio_src = bframe.locator("#audio-source").get_attribute("src", timeout=10000)
            if not audio_src:
                logger.warning("Could not obtain audio source URL.")
                continue

            logger.info("Downloading challenge audio...")
            resp = requests.get(audio_src, timeout=15)
            if resp.status_code != 200 or len(resp.content) < 100:
                logger.warning("Failed to download audio challenge (status: %d)", resp.status_code)
                continue

            # Transcribe audio with Whisper
            whisper = get_whisper()
            audio_file = io.BytesIO(resp.content)
            segments, _ = whisper.transcribe(audio_file, beam_size=5)
            transcribed_text = " ".join([s.text for s in segments]).strip().lower()
            logger.info("Transcribed reCAPTCHA audio text: '%s'", transcribed_text)

            if not transcribed_text:
                logger.warning("Empty transcription from audio challenge.")
                continue

            # Type transcription with human-like per-character delay
            response_field = bframe.locator("#audio-response")
            response_field.click()
            _human_delay(0.3, 0.6)
            response_field.fill("")  # clear first
            for char in transcribed_text:
                response_field.type(char, delay=random.randint(50, 150))

            _human_delay(0.5, 1.5)
            bframe.locator("#recaptcha-verify-button").click()
            _human_delay(2.0, 4.0)

            # Check if verified
            if _is_recaptcha_checked(anchor_frame):
                logger.info("reCAPTCHA successfully solved via audio challenge!")
                return True

            # If there's an error message inside the challenge
            err_msg = bframe.locator(".rc-audiochallenge-error-message").all_inner_texts()
            if err_msg:
                logger.warning("reCAPTCHA audio verification error: %s", err_msg)

        except Exception as exc:
            logger.warning("Error during reCAPTCHA audio solve attempt %d: %s", attempt, exc)
            _human_delay(1.0, 2.0)

    return False


def schedule_meals_web(
    username: str,
    password: str,
    target_date: datetime,
    restaurant_id: int,
    is_veg: bool,
    meals: list[str],
) -> dict[str, bool]:
    """
    Submits a meal scheduling request via Playwright and handles all captchas.

    Args:
        username: CPF or student registration number (matrícula)
        password: Portal password
        target_date: Target date to schedule
        restaurant_id: 1 for Campus I, 2 (or 41) for Campus II
        is_veg: True for vegetarian option
        meals: List of meal codes ('CAFE', 'ALMOCO', 'JANTAR', 'coffee', 'lunch', 'dinner')

    Returns:
        dict mapping meal_code -> bool success status
    """
    results = {m: False for m in meals}
    date_str = target_date.strftime("%d/%m/%Y")
    rest_id_str = RESTAURANT_PORTAL_IDS.get(restaurant_id, str(restaurant_id))

    logger.info("Starting automated web scheduling for %s at restaurant %s. Meals: %s", date_str, rest_id_str, meals)

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--window-size=1280,900",
            ]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        page = context.new_page()
        # Automatically accept confirmation dialogs (e.g. dinner time limit reminder)
        page.on("dialog", lambda dialog: dialog.accept())

        try:
            # Step 1: Login
            logger.info("Navigating to login page...")
            page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
            page.fill("input[name='j_username']", username)
            page.fill("input[name='j_password']", password)
            logger.info("Submitting login credentials...")
            with page.expect_navigation(wait_until="networkidle", timeout=30000):
                page.click("button[type='submit'], input[type='submit']")

            # Validate authentication result
            if "index.html" in page.url or page.locator("input[name='j_username']").count() > 0:
                err_text = page.locator(".pill.danger, .pill.error").all_inner_texts()
                raise RuntimeError(
                    f"Authentication failed on portal: {err_text if err_text else 'still on login page'}"
                )

            # Step 2: Open scheduling form
            logger.info("Opening scheduling form: %s", FORM_URL)
            page.goto(FORM_URL, wait_until="networkidle", timeout=30000)

            if "index.html" in page.url:
                raise RuntimeError("Redirected to login page when accessing scheduling form. Session was lost.")

            # Step 3: Fill dates
            page.wait_for_selector("#data", state="visible", timeout=15000)
            page.fill("#data", date_str)
            page.fill("#periodo_fim", date_str)

            # Step 4: Select restaurant and wait for meals AJAX response
            logger.info("Selecting restaurant %s and waiting for available meals...", rest_id_str)
            with page.expect_response(lambda r: "findBeneficios.json" in r.url, timeout=15000):
                page.select_option("#restaurante", rest_id_str)

            time.sleep(1)

            # Step 5: Check requested meals
            checked_any = False
            for meal in meals:
                meal_val = MEAL_PORTAL_IDS.get(meal)
                if not meal_val:
                    logger.warning("Unknown meal code: %s", meal)
                    continue

                cb = page.locator(f"#checkTipoRefeicao{meal_val}")
                if cb.count() > 0:
                    cb.check(force=True)
                    if not cb.is_checked():
                        page.eval_on_selector(f"#checkTipoRefeicao{meal_val}", "el => el.checked = true")
                    logger.info("Meal %s (ID: %s) selected. Checked: %s", meal, meal_val, cb.is_checked())
                    checked_any = True
                else:
                    logger.warning("Meal checkbox #checkTipoRefeicao%s not found for %s", meal_val, meal)

            if not checked_any:
                logger.error("No valid meal checkboxes could be checked on the form.")
                browser.close()
                return results

            # Step 6: Set vegetarian preference
            if is_veg:
                page.check("#opcaoVegetariana_true", force=True)
            else:
                page.check("#opcaoVegetariana_false", force=True)

            # Step 7: Solve internal text captcha (with 6-char verification loop)
            logger.info("Solving internal image captcha...")
            captcha_code = ""
            for attempt in range(1, 11):
                captcha_img = page.locator("#captchaImg")
                captcha_bytes = captcha_img.screenshot()
                code = solve_text_captcha(captcha_bytes)
                logger.debug("Captcha read attempt %d: '%s' (len: %d)", attempt, code, len(code))
                if len(code) == 6:
                    captcha_code = code
                    break
                logger.info("Captcha length != 6 ('%s'). Reloading image...", code)
                page.click("#refreshCaptchaBtn")
                time.sleep(1)

            if not captcha_code:
                logger.error("Could not obtain a valid 6-character captcha after 10 attempts.")
                browser.close()
                return results

            logger.info("Internal captcha solved: '%s'", captcha_code)
            page.fill("#captcha", captcha_code)

            # Step 8: Solve Google reCAPTCHA v2
            recaptcha_passed = solve_recaptcha(page)
            if not recaptcha_passed:
                logger.error("Failed to solve Google reCAPTCHA v2.")
                browser.close()
                return results

            # Step 9: Submit form
            logger.info("Submitting scheduling form...")
            page.click("#btnSubmit")
            page.wait_for_timeout(4000)

            # Step 10: Check results
            page.screenshot(path="web_schedule_last_result.png")
            body_text = page.inner_text("body").lower()
            current_url = page.url

            # Look for success markers:
            # - Table "Resultado da solicitação de agendamentos" with "Agendado com sucesso"
            # - Redirect to list page
            # - Success alert text
            if "agendado com sucesso" in body_text or "sucesso" in body_text or "action=list" in current_url:
                logger.info("Meal scheduling successfully processed for %s!", date_str)
                for meal in meals:
                    results[meal] = True
            elif "agendamento com estes dados" in body_text or ("já existe" in body_text and "agendamento" in body_text) or "já possui" in body_text:
                logger.info("Meal is already scheduled for %s ('Já existe um agendamento com estes dados'). Marking as OK.", date_str)
                for meal in meals:
                    results[meal] = True
            else:
                visible_errors = page.locator(".pill.error:not(.hidden)").all_inner_texts()
                logger.error("Scheduling submission failed. Visible errors: %s", visible_errors)

        except Exception as exc:
            logger.error("Exception during web scheduling: %s", exc)
            try:
                logger.error("Error occurred at page URL: %s", page.url)
                page.screenshot(path="web_schedule_error.png")
            except Exception:
                pass
        finally:
            browser.close()

    return results


def run_web_schedule(
    username: str,
    password: str,
    target_date: datetime,
    restaurant_id: int,
    is_veg: bool,
    meals: list[str],
) -> dict[str, bool]:
    """Entry point compatible with scheduler.py."""
    return schedule_meals_web(
        username=username,
        password=password,
        target_date=target_date,
        restaurant_id=restaurant_id,
        is_veg=is_veg,
        meals=meals,
    )
