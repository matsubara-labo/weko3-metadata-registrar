from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    TimeoutException,
)

from importers.selenium_auto_register import (
    CHECK_COMPONENT_SELECTOR,
    CHECK_RECORD_DOI_INPUT_SELECTOR,
    CHECK_RECORD_ROW_SELECTOR,
    CHECK_SUMMARY_ROW_SELECTOR,
    WEKO_ERROR_ALERT_SELECTOR,
    SelectorCandidate,
    WekoPageError,
    assert_no_check_errors,
    wait_for_step_ready_or_page_error,
)

BUTTON = SelectorCandidate(by="css selector", value="#button")
ZIP_PATH = Path("output/zip_data/sample.zip")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeNode:
    def __init__(
        self,
        text: str = "",
        displayed: bool = True,
        enabled: bool = True,
        children: dict[str, list[FakeNode]] | None = None,
    ) -> None:
        self.text = text
        self.displayed = displayed
        self.enabled = enabled
        self.children = children or {}
        self.clicked = False

    def is_displayed(self) -> bool:
        return self.displayed

    def is_enabled(self) -> bool:
        return self.enabled

    def get_attribute(self, name: str) -> str | None:
        if name == "disabled" and not self.enabled:
            return "true"
        return None

    def find_elements(self, by: str, value: str) -> list[FakeNode]:
        return list(self.children.get(value, []))

    def click(self) -> None:
        self.clicked = True


class FakeDriver:
    session_id = "fake"
    current_url = "https://weko.example/admin/items/import/"
    title = "WEKO"

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.timeline: dict[str, list[tuple[float, list[FakeNode]]]] = {}

    def show(self, selector: str, nodes: list[FakeNode], at: float = 0.0) -> None:
        self.timeline.setdefault(selector, []).append((at, nodes))

    def find_elements(self, by: str, value: str) -> list[FakeNode]:
        current: list[FakeNode] = []
        for appears_at, nodes in self.timeline.get(value, []):
            if self.clock.now >= appears_at:
                current = nodes
        return list(current)

    def find_element(self, by: str, value: str) -> FakeNode:
        elements = self.find_elements(by, value)
        if not elements:
            raise NoSuchElementException(value)
        return elements[0]


def check_row(number: int, detail: str, has_error: bool) -> FakeNode:
    cells = [FakeNode(str(number)), FakeNode("item"), FakeNode(detail)]
    doi_input = FakeNode(enabled=not has_error)
    return FakeNode(
        children={"td": cells, CHECK_RECORD_DOI_INPUT_SELECTOR: [doi_input]}
    )


def show_check_tab(
    driver: FakeDriver, summary: list[str], rows: list[FakeNode], at: float = 0.0
) -> None:
    driver.show(CHECK_COMPONENT_SELECTOR, [FakeNode()], at)
    driver.show(CHECK_SUMMARY_ROW_SELECTOR, [FakeNode(text) for text in summary], at)
    driver.show(CHECK_RECORD_ROW_SELECTOR, rows, at)


def summary_with_errors(errors: str) -> list[str]:
    return [
        "Total: 3",
        "New Item: 3",
        "Update Item: 0",
        f"Check Error: {errors}",
        "Warning: 0",
    ]


class PageErrorWaitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        patcher = patch("importers.selenium_auto_register.time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.driver = FakeDriver(self.clock)

    def wait_for_load(self, timeout_ms: int = 60_000) -> FakeNode:
        return wait_for_step_ready_or_page_error(
            self.driver,
            (BUTTON,),
            ZIP_PATH,
            "load",
            timeout_ms,
            extra_check=lambda: assert_no_check_errors(self.driver, ZIP_PATH),
        )

    def test_error_alert_raises_page_error_quickly(self) -> None:
        self.driver.show(
            WEKO_ERROR_ALERT_SELECTOR, [FakeNode("× Unexpected failure")], at=1.0
        )

        with self.assertRaisesRegex(WekoPageError, "Unexpected failure"):
            self.wait_for_load()

        self.assertLessEqual(self.clock.now, 1.5)

    def test_japanese_message_in_page_body_is_fatal(self) -> None:
        self.driver.show("body", [FakeNode("他の端末でインポートを実行中です。")])

        with self.assertRaisesRegex(WekoPageError, "インポートを実行中"):
            self.wait_for_load()

        self.assertEqual(self.clock.now, 0.0)

    def test_check_errors_raise_with_row_numbers(self) -> None:
        rows = [
            check_row(1, "Register", has_error=False),
            check_row(2, "Error: Title is required.", has_error=True),
            check_row(3, "Error: Invalid date.", has_error=True),
        ]
        show_check_tab(self.driver, summary_with_errors("2"), rows, at=2.0)
        self.driver.show("#button", [FakeNode(enabled=False)])

        with self.assertRaises(WekoPageError) as raised:
            self.wait_for_load()

        message = str(raised.exception)
        self.assertIn("2 error record(s)", message)
        self.assertIn("row 2: Error: Title is required.", message)
        self.assertIn("row 3: Error: Invalid date.", message)
        self.assertNotIn("row 1:", message)
        self.assertLessEqual(self.clock.now, 2.5)

    def test_zero_check_errors_and_enabled_button_returns(self) -> None:
        show_check_tab(
            self.driver,
            summary_with_errors("0"),
            [check_row(1, "Register", has_error=False)],
        )
        button = FakeNode()
        self.driver.show("#button", [button])

        self.assertIs(self.wait_for_load(), button)

    def test_unparsable_summary_keeps_waiting_until_timeout(self) -> None:
        show_check_tab(self.driver, ["Total", "New", "Update", "Check Error: -"], [])
        self.driver.show("#button", [FakeNode(enabled=False)])

        with self.assertRaises(TimeoutException):
            self.wait_for_load(timeout_ms=3_000)

        self.assertAlmostEqual(self.clock.now, 3.0)

    def test_import_in_progress_during_result_wait_raises_before_timeout(
        self,
    ) -> None:
        self.driver.show("#button", [FakeNode(enabled=False)])
        self.driver.show(
            WEKO_ERROR_ALERT_SELECTOR,
            [FakeNode("× Import is in progress.")],
            at=5.0,
        )

        with self.assertRaisesRegex(
            WekoPageError, "import failed.*Import is in progress"
        ):
            wait_for_step_ready_or_page_error(
                self.driver, (BUTTON,), ZIP_PATH, "import", 480_000
            )

        self.assertLessEqual(self.clock.now, 5.5)

    def test_lost_session_is_raised_immediately(self) -> None:
        def lost_session(by: str, value: str) -> None:
            raise InvalidSessionIdException("invalid session id")

        self.driver.find_element = lost_session

        with self.assertRaises(InvalidSessionIdException):
            wait_for_step_ready_or_page_error(
                self.driver, (BUTTON,), ZIP_PATH, "import", 480_000
            )

        self.assertEqual(self.clock.now, 0.0)


if __name__ == "__main__":
    unittest.main()
