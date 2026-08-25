# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "selenium>=4.33.0",
#   "python-dotenv>=1.1.0",
# ]
# ///
#
from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    InvalidSessionIdException,
    JavascriptException,
    NoSuchWindowException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver, WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from urllib3.exceptions import ProtocolError

from generation.registration_config import load_registration_settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRATION_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "metadata_registration.json"
)
DEFAULT_SELECTOR_CONFIG_PATH = REPOSITORY_ROOT / "config" / "weko_ui_selectors.json"
BY_LOOKUP = {
    "css selector": By.CSS_SELECTOR,
    "xpath": By.XPATH,
    "name": By.NAME,
    "id": By.ID,
}
WEKO_FATAL_MESSAGE_KEYWORDS = (
    "internal server error",
    "the tsv file could not be read",
)
POLL_INTERVAL_SECONDS = 2
MAX_IMPORT_ATTEMPTS = 4
DRIVER_RETRY_DELAY_SECONDS = 4


@dataclass(frozen=True)
class SelectorCandidate:
    by: str
    value: str

    def as_locator(self) -> tuple[str, str]:
        if self.by not in BY_LOOKUP:
            raise ValueError(f"Unsupported selector strategy: {self.by}")
        return BY_LOOKUP[self.by], self.value


@dataclass(frozen=True)
class WekoSelectors:
    email_input: tuple[SelectorCandidate, ...]
    password_input: tuple[SelectorCandidate, ...]
    login_button: tuple[SelectorCandidate, ...]
    file_input: tuple[SelectorCandidate, ...]
    load_button: tuple[SelectorCandidate, ...]
    import_button: tuple[SelectorCandidate, ...]
    download_button: tuple[SelectorCandidate, ...]


@dataclass(frozen=True)
class WekoImportConfig:
    base_dir: Path = REPOSITORY_ROOT
    weko_base_url: str | None = None
    registration_config_path: Path = DEFAULT_REGISTRATION_CONFIG_PATH
    zip_dir: Path | None = None
    download_dir: Path | None = None
    headless: bool = False
    ui_timeout_ms: int = 45_000
    load_timeout_ms: int = 240_000
    import_timeout_ms: int = 480_000
    download_timeout_ms: int = 120_000
    post_login_timeout_ms: int = 45_000
    limit: int | None = None
    delete_zip_after_import: bool = False
    keep_zip_after_import: bool = False
    processed_zip_dir: Path | None = None
    selector_config_path: Path | None = DEFAULT_SELECTOR_CONFIG_PATH
    selectors: WekoSelectors | None = None

    @property
    def login_url(self) -> str:
        return f"{self._required_base_url()}/login/?next=%2F"

    @property
    def import_url(self) -> str:
        return f"{self._required_base_url()}/admin/items/import/"

    def _required_base_url(self) -> str:
        if self.weko_base_url is None:
            raise RuntimeError("WEKO base URL has not been resolved")
        return self.weko_base_url.rstrip("/")

    def resolved_zip_dir(self) -> Path:
        return self.zip_dir or self.base_dir / "output" / "zip_data"

    def resolved_download_dir(self) -> Path:
        return self.download_dir or self.base_dir / "output" / "import_results"

    def resolved_processed_zip_dir(self) -> Path:
        return self.processed_zip_dir or self.base_dir / "output" / "uploaded_zip_data"


def load_selector_config(selector_config_path: Path) -> WekoSelectors:
    if not selector_config_path.exists():
        raise FileNotFoundError(
            f"Selector config was not found: {selector_config_path}"
        )

    with selector_config_path.open("r", encoding="utf-8") as file_obj:
        raw = json.load(file_obj)

    def parse_candidates(key: str) -> tuple[SelectorCandidate, ...]:
        return tuple(
            SelectorCandidate(by=item["by"], value=item["value"]) for item in raw[key]
        )

    return WekoSelectors(
        email_input=parse_candidates("email_input"),
        password_input=parse_candidates("password_input"),
        login_button=parse_candidates("login_button"),
        file_input=parse_candidates("file_input"),
        load_button=parse_candidates("load_button"),
        import_button=parse_candidates("import_button"),
        download_button=parse_candidates("download_button"),
    )


def resolve_selectors(config: WekoImportConfig) -> WekoSelectors:
    if config.selectors is not None:
        return config.selectors
    return load_selector_config(
        config.selector_config_path or DEFAULT_SELECTOR_CONFIG_PATH
    )


def sorted_zip_files(zip_dir: Path) -> list[Path]:
    return sorted(path for path in zip_dir.glob("*.zip") if path.is_file())


def wait_for_candidates(
    driver: WebDriver,
    candidates: tuple[SelectorCandidate, ...],
    timeout_ms: int,
    condition_factory,
) -> WebElement:
    last_error: Exception | None = None
    attempts = max(1, len(candidates))
    timeout_per_selector = max(1.0, timeout_ms / 1000 / attempts)

    for candidate in candidates:
        locator = candidate.as_locator()
        try:
            return WebDriverWait(driver, timeout_per_selector).until(
                condition_factory(locator)
            )
        except Exception as exc:
            last_error = exc

    candidate_descriptions = [
        f"{candidate.by}={candidate.value}" for candidate in candidates
    ]
    raise TimeoutException(
        f"Could not resolve any selector from: {candidate_descriptions}"
    ) from last_error


def any_candidate_present(
    driver: WebDriver, candidates: tuple[SelectorCandidate, ...]
) -> bool:
    for candidate in candidates:
        try:
            if driver.find_elements(*candidate.as_locator()):
                return True
        except Exception:
            continue
    return False


def wait_for_visible(
    driver: WebDriver, candidates: tuple[SelectorCandidate, ...], timeout_ms: int
) -> WebElement:
    return wait_for_candidates(
        driver, candidates, timeout_ms, EC.visibility_of_element_located
    )


def wait_for_present(
    driver: WebDriver, candidates: tuple[SelectorCandidate, ...], timeout_ms: int
) -> WebElement:
    return wait_for_candidates(
        driver, candidates, timeout_ms, EC.presence_of_element_located
    )


def wait_for_clickable(
    driver: WebDriver, candidates: tuple[SelectorCandidate, ...], timeout_ms: int
) -> WebElement:
    return wait_for_candidates(
        driver, candidates, timeout_ms, EC.element_to_be_clickable
    )


def wait_for_enabled(
    driver: WebDriver, candidates: tuple[SelectorCandidate, ...], timeout_ms: int
) -> WebElement:
    last_error: Exception | None = None
    attempts = max(1, len(candidates))
    timeout_per_selector = max(1.0, timeout_ms / 1000 / attempts)

    for candidate in candidates:
        locator = candidate.as_locator()
        try:

            def enabled_element(d: WebDriver) -> WebElement | bool:
                element = d.find_element(*locator)
                return element if element_is_enabled(element) else False

            return WebDriverWait(driver, timeout_per_selector).until(enabled_element)
        except Exception as exc:
            last_error = exc

    candidate_descriptions = [
        f"{candidate.by}={candidate.value}" for candidate in candidates
    ]
    raise TimeoutException(
        f"Could not resolve any enabled selector from: {candidate_descriptions}"
    ) from last_error


def element_is_enabled(element: WebElement) -> bool:
    disabled = element.get_attribute("disabled")
    aria_disabled = element.get_attribute("aria-disabled")
    return element.is_enabled() and disabled is None and aria_disabled != "true"


def click_element(driver: WebDriver, element: WebElement) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    try:
        element.click()
        return
    except (
        ElementClickInterceptedException,
        JavascriptException,
        StaleElementReferenceException,
    ):
        pass
    driver.execute_script("arguments[0].click();", element)


def click_when_ready(
    driver: WebDriver,
    candidates: tuple[SelectorCandidate, ...],
    timeout_ms: int,
    description: str,
) -> None:
    try:
        element = wait_for_clickable(driver, candidates, timeout_ms)
        click_element(driver, element)
        return
    except TimeoutException:
        pass

    try:
        element = wait_for_enabled(driver, candidates, timeout_ms)
        click_element(driver, element)
        return
    except Exception as exc:
        candidate_descriptions = [
            f"{candidate.by}={candidate.value}" for candidate in candidates
        ]
        messages = collect_page_messages(driver)
        message_suffix = f"; page_messages={messages}" if messages else ""
        raise TimeoutException(
            f"Could not click {description} using selectors {candidate_descriptions}; "
            f"{describe_driver_state(driver)}{message_suffix}"
        ) from exc


def prepare_file_input(driver: WebDriver, file_input: WebElement) -> WebElement:
    try:
        driver.execute_script(
            """
            const input = arguments[0];
            input.removeAttribute('hidden');
            input.removeAttribute('disabled');
            input.style.display = 'block';
            input.style.visibility = 'visible';
            input.style.opacity = '1';
            input.style.position = 'fixed';
            input.style.left = '0';
            input.style.top = '0';
            input.style.zIndex = '2147483647';
            """,
            file_input,
        )
    except JavascriptException:
        return file_input
    return file_input


def wait_for_download(
    download_dir: Path, previous_files: set[str], timeout_ms: int
) -> Path:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        current_files = {path.name for path in download_dir.iterdir() if path.is_file()}
        new_files = sorted(current_files - previous_files)
        completed = [
            name
            for name in new_files
            if not name.endswith((".crdownload", ".tmp", ".part"))
        ]
        if completed:
            return download_dir / completed[0]
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutException(
        f"Timed out waiting for a completed download in {download_dir}"
    )


def collect_page_messages(driver: WebDriver) -> list[str]:
    messages: list[str] = []
    selectors = ("#errors", ".alert", ".alert-danger", ".alert-warning")
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        for element in elements:
            text = " ".join(element.text.split())
            if text and text not in messages:
                messages.append(text)

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        body_text = ""
    normalized_body = " ".join(body_text.split())
    for keyword in WEKO_FATAL_MESSAGE_KEYWORDS:
        if keyword in normalized_body.lower() and keyword not in [
            message.lower() for message in messages
        ]:
            messages.append(keyword)

    return messages


def assert_no_weko_page_error(driver: WebDriver, zip_path: Path, phase: str) -> None:
    messages = collect_page_messages(driver)
    fatal_messages = [
        message
        for message in messages
        if any(keyword in message.lower() for keyword in WEKO_FATAL_MESSAGE_KEYWORDS)
    ]
    if fatal_messages:
        raise TimeoutException(
            f"WEKO {phase} failed for {zip_path}: {' | '.join(fatal_messages)}; "
            f"{describe_driver_state(driver)}"
        )


def wait_for_step_ready_or_page_error(
    driver: WebDriver,
    candidates: tuple[SelectorCandidate, ...],
    zip_path: Path,
    phase: str,
    timeout_ms: int,
) -> None:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        assert_no_weko_page_error(driver, zip_path, phase)
        for candidate in candidates:
            try:
                element = driver.find_element(*candidate.as_locator())
            except Exception:
                continue
            if element.is_displayed() and element_is_enabled(element):
                return
        time.sleep(POLL_INTERVAL_SECONDS)

    messages = collect_page_messages(driver)
    message_suffix = f"; page_messages={messages}" if messages else ""
    raise TimeoutException(
        f"WEKO {phase} did not become ready for {zip_path}; {describe_driver_state(driver)}{message_suffix}"
    )


def unique_destination_path(destination_dir: Path, original_name: str) -> Path:
    candidate = destination_dir / original_name
    if not candidate.exists():
        return candidate

    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    for index in range(1, 10_000):
        candidate = destination_dir / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(
        f"Could not determine a unique destination path for {original_name} in {destination_dir}"
    )


def finalize_imported_zip(zip_path: Path, config: WekoImportConfig) -> Path | None:
    if config.delete_zip_after_import:
        zip_path.unlink()
        return None

    if config.keep_zip_after_import:
        return zip_path

    processed_dir = config.resolved_processed_zip_dir()
    processed_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination_path(processed_dir, zip_path.name)
    if destination.resolve() == zip_path.resolve():
        return zip_path

    shutil.move(str(zip_path), str(destination))
    return destination


def describe_driver_state(driver: WebDriver) -> str:
    details: list[str] = []
    details.append(f"session_id={getattr(driver, 'session_id', None)!r}")
    try:
        details.append(f"current_url={driver.current_url}")
    except Exception as exc:
        details.append(f"current_url=<unavailable:{type(exc).__name__}>")
    try:
        details.append(f"title={driver.title!r}")
    except Exception as exc:
        details.append(f"title=<unavailable:{type(exc).__name__}>")
    return "; ".join(details)


def driver_session_lost(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (InvalidSessionIdException, NoSuchWindowException)):
            return True
        if (
            isinstance(current, WebDriverException)
            and "invalid session id" in str(current).lower()
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def driver_connection_lost(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(
            current,
            (
                ConnectionResetError,
                ConnectionAbortedError,
                BrokenPipeError,
                http.client.RemoteDisconnected,
                ProtocolError,
            ),
        ):
            return True
        if isinstance(current, OSError) and getattr(current, "winerror", None) == 10054:
            return True
        if isinstance(current, WebDriverException):
            message = str(current).lower()
            if any(
                keyword in message
                for keyword in (
                    "connection reset",
                    "remote host",
                    "disconnected",
                    "failed to establish a new connection",
                    "connection refused",
                )
            ):
                return True
        current = current.__cause__ or current.__context__
    return False


def build_chrome_options(download_dir: Path, headless: bool) -> Options:
    options = Options()
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-insecure-localhost")
    if headless:
        options.add_argument("--headless=new")
    prefs = {
        "download.default_directory": str(download_dir.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)
    return options


def create_driver(config: WekoImportConfig, download_dir: Path) -> WebDriver:
    driver = webdriver.Chrome(
        options=build_chrome_options(download_dir, config.headless)
    )
    if not config.headless:
        driver.maximize_window()
    return driver


def load_env_settings(base_dir: Path) -> tuple[str, str]:
    env_path = base_dir / ".env"
    load_dotenv(env_path)
    username = os.environ.get("WEKO_EMAIL")
    password = os.environ.get("WEKO_PASSWORD")
    if not username or not password:
        raise RuntimeError(f"WEKO_EMAIL or WEKO_PASSWORD is not set in {env_path}")
    return username, password


def normalize_weko_base_url(base_url: str, source: str) -> str:
    normalized = base_url.rstrip("/")
    if not normalized:
        raise RuntimeError(f"WEKO base URL from {source} is empty")
    return normalized


def resolve_weko_base_url(config: WekoImportConfig) -> str:
    if config.weko_base_url is not None:
        return normalize_weko_base_url(config.weko_base_url, "CLI")

    load_dotenv(config.base_dir / ".env")
    env_base_url = os.environ.get("WEKO_URL")
    if env_base_url:
        return normalize_weko_base_url(env_base_url, "WEKO_URL")

    settings = load_registration_settings(config.registration_config_path)
    return normalize_weko_base_url(
        settings.weko_base_url, str(config.registration_config_path)
    )


def login(driver: WebDriver, config: WekoImportConfig) -> None:
    selectors = config.selectors or resolve_selectors(config)
    username, password = load_env_settings(config.base_dir)
    driver.get(config.login_url)
    wait_for_visible(driver, selectors.email_input, config.ui_timeout_ms).send_keys(
        username
    )
    wait_for_visible(driver, selectors.password_input, config.ui_timeout_ms).send_keys(
        password
    )
    click_when_ready(
        driver, selectors.login_button, config.ui_timeout_ms, "login button"
    )
    deadline = time.time() + config.post_login_timeout_ms / 1000
    while time.time() < deadline:
        current_url = ""
        try:
            current_url = driver.current_url.lower()
        except Exception:
            pass
        if "login" not in current_url:
            return
        if not any_candidate_present(
            driver, selectors.email_input
        ) and not any_candidate_present(driver, selectors.password_input):
            return
        time.sleep(POLL_INTERVAL_SECONDS)

    driver.get(config.import_url)
    try:
        wait_for_present(driver, selectors.file_input, config.ui_timeout_ms)
        return
    except TimeoutException:
        messages = collect_page_messages(driver)
        message_suffix = f"; page_messages={messages}" if messages else ""
        raise TimeoutException(
            f"WEKO login did not complete; {describe_driver_state(driver)}{message_suffix}"
        )


def import_one_zip(
    driver: WebDriver, zip_path: Path, download_dir: Path, config: WekoImportConfig
) -> Path:
    selectors = config.selectors or resolve_selectors(config)
    driver.get(config.import_url)
    try:
        file_input = wait_for_present(
            driver, selectors.file_input, config.ui_timeout_ms
        )
    except TimeoutException as exc:
        raise TimeoutException(f"{exc.msg}; {describe_driver_state(driver)}") from exc
    prepare_file_input(driver, file_input).send_keys(str(zip_path.resolve()))
    click_when_ready(driver, selectors.load_button, config.ui_timeout_ms, "load button")
    wait_for_step_ready_or_page_error(
        driver,
        selectors.import_button,
        zip_path,
        "load",
        config.load_timeout_ms,
    )
    click_when_ready(
        driver, selectors.import_button, config.load_timeout_ms, "import button"
    )
    assert_no_weko_page_error(driver, zip_path, "import")
    previous_files = {path.name for path in download_dir.iterdir() if path.is_file()}
    click_when_ready(
        driver, selectors.download_button, config.import_timeout_ms, "download button"
    )
    return wait_for_download(download_dir, previous_files, config.download_timeout_ms)


def run_import(config: WekoImportConfig) -> list[tuple[Path, Path]]:
    config = replace(config, weko_base_url=resolve_weko_base_url(config))
    config = replace(config, selectors=resolve_selectors(config))
    zip_dir = config.resolved_zip_dir()
    if not zip_dir.exists():
        raise FileNotFoundError(f"Zip directory was not found: {zip_dir}")

    download_dir = config.resolved_download_dir()
    download_dir.mkdir(parents=True, exist_ok=True)

    zip_files = sorted_zip_files(zip_dir)
    if config.limit is not None:
        zip_files = zip_files[: config.limit]
    if not zip_files:
        return []

    results: list[tuple[Path, Path]] = []
    total = len(zip_files)
    for index, zip_path in enumerate(zip_files, start=1):
        print(f"[{index}/{total}] importing {zip_path}")
        last_error: Exception | None = None
        for attempt in range(1, MAX_IMPORT_ATTEMPTS + 1):
            driver: WebDriver | None = None
            try:
                driver = create_driver(config, download_dir)
                login(driver, config)
                downloaded_file = import_one_zip(driver, zip_path, download_dir, config)
                results.append((zip_path, downloaded_file))
                finalized_zip_path = finalize_imported_zip(zip_path, config)
                print(f"[{index}/{total}] imported={zip_path} result={downloaded_file}")
                if finalized_zip_path is None:
                    print(f"[{index}/{total}] deleted={zip_path}")
                elif finalized_zip_path != zip_path:
                    print(f"[{index}/{total}] moved={zip_path} -> {finalized_zip_path}")
                break
            except Exception as exc:
                last_error = exc
                if attempt == MAX_IMPORT_ATTEMPTS or not (
                    driver_session_lost(exc) or driver_connection_lost(exc)
                ):
                    raise
                print(
                    f"[{index}/{total}] retrying after driver disconnect on attempt {attempt}: {type(exc).__name__}"
                )
                time.sleep(DRIVER_RETRY_DELAY_SECONDS)
            finally:
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
        else:
            if last_error is not None:
                raise last_error

    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import WEKO metadata zip files with Selenium."
    )
    parser.add_argument("--base-dir", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument(
        "--weko-base-url",
        help="WEKO base URL. Overrides WEKO_URL and registration config.",
    )
    parser.add_argument(
        "--registration-config",
        type=Path,
        default=DEFAULT_REGISTRATION_CONFIG_PATH,
        help="Registration config JSON file.",
    )
    parser.add_argument(
        "--selector-config", type=Path, help="Selector config json file."
    )
    parser.add_argument("--zip-dir", type=Path)
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--ui-timeout-ms", type=int, default=45_000)
    parser.add_argument("--load-timeout-ms", type=int, default=240_000)
    parser.add_argument("--import-timeout-ms", type=int, default=480_000)
    parser.add_argument("--download-timeout-ms", type=int, default=120_000)
    parser.add_argument("--post-login-timeout-ms", type=int, default=45_000)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delete-zip-after-import", action="store_true")
    parser.add_argument("--keep-zip-after-import", action="store_true")
    parser.add_argument("--processed-zip-dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = WekoImportConfig(
        base_dir=args.base_dir,
        weko_base_url=args.weko_base_url,
        registration_config_path=args.registration_config,
        selector_config_path=args.selector_config,
        zip_dir=args.zip_dir,
        download_dir=args.download_dir,
        headless=args.headless,
        ui_timeout_ms=args.ui_timeout_ms,
        load_timeout_ms=args.load_timeout_ms,
        import_timeout_ms=args.import_timeout_ms,
        download_timeout_ms=args.download_timeout_ms,
        post_login_timeout_ms=args.post_login_timeout_ms,
        limit=args.limit,
        delete_zip_after_import=args.delete_zip_after_import,
        keep_zip_after_import=args.keep_zip_after_import,
        processed_zip_dir=args.processed_zip_dir,
    )

    results = run_import(config)
    if not results:
        print("No zip files were found to import.")
        return 0

    for zip_path, download_path in results:
        print(f"imported={zip_path} result={download_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
