from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.support import expected_conditions as EC

from importers.selenium_auto_register import (
    DEFAULT_SELECTOR_CONFIG_PATH,
    SelectorCandidate,
    click_when_ready,
    load_selector_config,
    wait_for_candidates,
    wait_for_clickable,
    wait_for_enabled,
)

FIRST = SelectorCandidate(by="css selector", value="#first")
SECOND = SelectorCandidate(by="css selector", value="#second")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeElement:
    def __init__(self, displayed: bool = True, enabled: bool = True) -> None:
        self.displayed = displayed
        self.enabled = enabled
        self.clicked = False

    def is_displayed(self) -> bool:
        return self.displayed

    def is_enabled(self) -> bool:
        return self.enabled

    def get_attribute(self, name: str) -> str | None:
        return None

    def click(self) -> None:
        self.clicked = True


class FakeDriver:
    session_id = "fake"
    current_url = "https://weko.example/admin/items/import/"
    title = "WEKO"

    def __init__(
        self, clock: FakeClock, elements: dict[str, tuple[float, FakeElement]]
    ):
        self.clock = clock
        self.elements = elements
        self.lookups: list[str] = []

    def find_element(self, by: str, value: str) -> FakeElement:
        self.lookups.append(value)
        appears_at, element = self.elements.get(value, (float("inf"), None))
        if element is None or self.clock.now < appears_at:
            raise NoSuchElementException(value)
        return element

    def find_elements(self, by: str, value: str) -> list[FakeElement]:
        try:
            return [self.find_element(by, value)]
        except NoSuchElementException:
            return []

    def execute_script(self, script: str, *args) -> None:
        if "click()" in script:
            args[0].click()


class WaitForCandidatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        patcher = patch("importers.selenium_auto_register.time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_later_candidate_is_found_without_waiting_for_first_to_time_out(
        self,
    ) -> None:
        element = FakeElement()
        driver = FakeDriver(self.clock, {"#second": (1.0, element)})

        result = wait_for_clickable(driver, (FIRST, SECOND), 10_000)

        self.assertIs(result, element)
        self.assertLessEqual(self.clock.now, 1.5)
        self.assertEqual(driver.lookups[:2], ["#first", "#second"])

    def test_first_matching_candidate_wins_in_candidate_order(self) -> None:
        first = FakeElement()
        second = FakeElement()
        driver = FakeDriver(self.clock, {"#first": (0, first), "#second": (0, second)})

        self.assertIs(wait_for_enabled(driver, (FIRST, SECOND), 1_000), first)

    def test_total_wait_does_not_exceed_timeout(self) -> None:
        driver = FakeDriver(self.clock, {})

        with self.assertRaisesRegex(TimeoutException, "#first.*#second"):
            wait_for_enabled(driver, (FIRST, SECOND), 3_000)

        self.assertAlmostEqual(self.clock.now, 3.0)

    def test_disabled_candidate_is_not_returned_until_enabled(self) -> None:
        element = FakeElement(enabled=False)
        driver = FakeDriver(self.clock, {"#first": (0, element)})

        with self.assertRaises(TimeoutException):
            wait_for_enabled(driver, (FIRST,), 1_000)
        element.enabled = True
        self.assertIs(wait_for_enabled(driver, (FIRST,), 1_000), element)

    def test_lost_session_is_raised_without_consuming_timeout(self) -> None:
        driver = FakeDriver(self.clock, {})

        def lost_session(by: str, value: str) -> None:
            raise InvalidSessionIdException("invalid session id")

        driver.find_element = lost_session

        with self.assertRaises(InvalidSessionIdException):
            wait_for_candidates(
                driver,
                (FIRST, SECOND),
                480_000,
                EC.presence_of_element_located,
            )

        self.assertEqual(self.clock.now, 0.0)


class ClickWhenReadyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        patcher = patch("importers.selenium_auto_register.time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_timeout_is_not_doubled_when_nothing_matches(self) -> None:
        driver = FakeDriver(self.clock, {})

        with self.assertRaisesRegex(TimeoutException, "load button"):
            click_when_ready(driver, (FIRST, SECOND), 4_000, "load button")

        self.assertAlmostEqual(self.clock.now, 4.0)

    def test_hidden_enabled_element_is_clicked_after_single_deadline(self) -> None:
        element = FakeElement(displayed=False)
        driver = FakeDriver(self.clock, {"#second": (0, element)})

        click_when_ready(driver, (FIRST, SECOND), 4_000, "import button")

        self.assertTrue(element.clicked)
        self.assertAlmostEqual(self.clock.now, 4.0)


class StepButtonSelectorTests(unittest.TestCase):
    def test_load_and_import_prefer_language_independent_selectors(self) -> None:
        selectors = load_selector_config(DEFAULT_SELECTOR_CONFIG_PATH)
        cases = (
            (selectors.load_button, "import_component", ("Next", "次へ")),
            (selectors.import_button, "check-component", ("Import", "インポート")),
        )
        for candidates, component, labels in cases:
            with self.subTest(component=component):
                first = candidates[0].value
                self.assertIn(f"' {component} '", first)
                self.assertIn("' glyphicon-download-alt '", first)
                self.assertNotRegex(first, r"normalize-space\(\.\)|text\(\)")
                text_fallback = candidates[1].value
                self.assertIn(f"' {component} '", text_fallback)
                for label in labels:
                    self.assertIn(f"'{label}'", text_fallback)
                self.assertTrue(re.match(r"^/html/body/", candidates[-1].value))


if __name__ == "__main__":
    unittest.main()
