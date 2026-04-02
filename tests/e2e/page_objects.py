"""Page object models for Whitelist Manager E2E tests."""
import time
from typing import List, Dict, Any
from playwright.sync_api import Page


class SplunkPage:
    """Base page object handling Splunk-specific UI quirks."""

    def __init__(self, page: Page, base_url: str = "http://localhost:8000"):
        """Initialize page object with Playwright page instance."""
        self.page = page
        self.base_url = base_url

    def goto(self, path: str) -> None:
        """Navigate to Splunk page and wait for content load."""
        self.page.goto(f"{self.base_url}{path}", wait_until="networkidle")
        self.wait_for_splunk_load()

    def wait_for_splunk_load(self) -> None:
        """Wait for Splunk panels to fully render and become interactive."""
        try:
            # Wait for at least one panel to appear
            self.page.wait_for_selector('div[class*="panel"]', timeout=5000)
            time.sleep(0.5)  # Extra buffer for animations and dynamic content
        except Exception:
            # Panels may load via iframes or delayed rendering
            pass

    def get_iframe_page(self, panel_name: str):
        """Get page context within an iframe (for HTML panels)."""
        iframe_locator = f'iframe[name*="{panel_name}"]'
        frame = self.page.frame_locator(iframe_locator).first
        return frame


class WhitelistManagerPage(SplunkPage):
    """Main whitelist manager dashboard page object."""

    def load_csv(self, csv_name: str) -> None:
        """Load a CSV file from detection rule dropdown."""
        # Wait for dropdown to be interactive
        self.page.wait_for_selector('select, div[class*="dropdown"]', timeout=5000)
        time.sleep(0.3)

        # Try to find and click detection rule select
        dropdowns = self.page.locators('select').all()
        if dropdowns:
            # If there's a select element, use it
            dropdowns[0].select_option(csv_name)
        else:
            # Otherwise try custom Splunk dropdown
            dropdown = self.page.locator('div[class*="dropdown"]').first
            if dropdown.is_visible():
                dropdown.click()
                self.page.wait_for_selector(f'text="{csv_name}"', timeout=5000)
                self.page.click(f'text="{csv_name}"')

        self.page.wait_for_load_state("networkidle", timeout=10000)

    def get_table_rows(self) -> List[Dict[str, List[str]]]:
        """Retrieve current table rows with cell data."""
        try:
            rows = self.page.locators('table tbody tr').all()
            result = []
            for row in rows:
                cells = row.locators('td').all()
                cell_texts = [cell.text_content() or "" for cell in cells]
                result.append({"cells": cell_texts})
            return result
        except Exception:
            return []

    def edit_cell(self, row_idx: int, col_idx: int, new_value: str) -> None:
        """Edit a cell value in the table."""
        try:
            # Select the cell (row_idx and col_idx are 1-based per Playwright convention)
            cell = self.page.locator(
                f'table tbody tr:nth-child({row_idx}) td:nth-child({col_idx})'
            ).first
            cell.click()
            time.sleep(0.2)

            # Try to fill input if it appears
            inputs = self.page.locators('input[type="text"]').all()
            if inputs:
                inputs[-1].fill(new_value)  # Fill the last input (likely the active cell)
                inputs[-1].blur()  # Trigger change detection
                time.sleep(0.3)
        except Exception as e:
            print(f"Failed to edit cell: {e}")

    def add_row(self) -> None:
        """Click 'Add Row' button to add a new row."""
        try:
            # Splunk uses span buttons, not <button> elements
            add_button = self.page.locator('span:has-text("Add Row")').first
            if add_button.is_visible():
                add_button.click()
                self.page.wait_for_selector('input', timeout=5000)
                time.sleep(0.3)
        except Exception as e:
            print(f"Failed to add row: {e}")

    def remove_row(self, row_idx: int, reason: str = "Test removal") -> None:
        """Remove a row by checking its checkbox and confirming removal."""
        try:
            # Select the row checkbox
            row = self.page.locator(f'table tbody tr:nth-child({row_idx})').first
            checkbox = row.locator('input[type="checkbox"]').first
            if checkbox.is_visible():
                checkbox.check()
                time.sleep(0.2)

            # Click Remove button
            remove_button = self.page.locator('span:has-text("Remove")').first
            if remove_button.is_visible():
                remove_button.click()
                time.sleep(0.3)

                # Fill reason if modal appears
                try:
                    textarea = self.page.locator('textarea[name="removal_reason"], textarea').first
                    if textarea.is_visible():
                        textarea.fill(reason)
                        time.sleep(0.2)
                except Exception:
                    pass

                # Click Confirm button
                confirm = self.page.locator('span:has-text("Confirm"), button:has-text("Confirm")').first
                if confirm.is_visible():
                    confirm.click()
                    time.sleep(0.5)
        except Exception as e:
            print(f"Failed to remove row: {e}")

    def save_changes(self, comment: str = "E2E test save") -> None:
        """Fill comment and save changes."""
        try:
            # Fill comment
            comment_fields = self.page.locators('textarea[name="comment"], textarea').all()
            if comment_fields:
                comment_fields[0].fill(comment)
                time.sleep(0.2)

            # Click Save button
            save_button = self.page.locator('span:has-text("Save")').first
            if save_button.is_visible():
                save_button.click()
                # Wait for success message
                try:
                    self.page.wait_for_selector(
                        'text="Saved successfully", text="Success", text="saved"',
                        timeout=10000
                    )
                except Exception:
                    time.sleep(1)  # Fallback wait
        except Exception as e:
            print(f"Failed to save changes: {e}")

    def get_audit_events(self) -> int:
        """Navigate to audit tab and get event count."""
        try:
            audit_link = self.page.locator('a:has-text("Audit"), span:has-text("Audit")').first
            if audit_link.is_visible():
                audit_link.click()
                self.page.wait_for_selector('table', timeout=5000)
                rows = self.page.locators('table tbody tr').all()
                return len(rows)
        except Exception:
            pass
        return 0

    def toggle_theme(self) -> None:
        """Toggle dark/light theme."""
        try:
            theme_button = self.page.locator('button[id="theme-toggle"], span:has-text("Theme")').first
            if theme_button.is_visible():
                theme_button.click()
                time.sleep(0.5)
        except Exception as e:
            print(f"Failed to toggle theme: {e}")


class ControlPanelPage(SplunkPage):
    """Admin control panel page object."""

    def get_approval_queue(self) -> int:
        """Retrieve approval queue item count."""
        try:
            queue_tab = self.page.locator('span:has-text("Approval"), span:has-text("Queue")').first
            if queue_tab.is_visible():
                queue_tab.click()
                self.page.wait_for_selector('table', timeout=5000)
                rows = self.page.locators('table tbody tr').all()
                return len(rows)
        except Exception:
            pass
        return 0

    def approve_request(self, request_idx: int, comment: str = "Approved by E2E test") -> None:
        """Approve a pending approval request."""
        try:
            row = self.page.locator(f'table tbody tr:nth-child({request_idx})').first
            approve_button = row.locator('span:has-text("Approve")').first
            if approve_button.is_visible():
                approve_button.click()
                time.sleep(0.3)

                # Fill approval comment if modal appears
                try:
                    textarea = self.page.locator('textarea[name="approval_comment"], textarea').first
                    if textarea.is_visible():
                        textarea.fill(comment)
                        time.sleep(0.2)
                except Exception:
                    pass

                # Submit
                submit = self.page.locator('span:has-text("Submit"), button:has-text("Submit")').first
                if submit.is_visible():
                    submit.click()
                    time.sleep(0.5)
        except Exception as e:
            print(f"Failed to approve request: {e}")

    def reject_request(self, request_idx: int, reason: str = "Rejected by E2E test") -> None:
        """Reject a pending approval request."""
        try:
            row = self.page.locator(f'table tbody tr:nth-child({request_idx})').first
            reject_button = row.locator('span:has-text("Reject")').first
            if reject_button.is_visible():
                reject_button.click()
                time.sleep(0.3)

                # Fill rejection reason if modal appears
                try:
                    textarea = self.page.locator('textarea[name="rejection_reason"], textarea').first
                    if textarea.is_visible():
                        textarea.fill(reason)
                        time.sleep(0.2)
                except Exception:
                    pass

                # Submit
                submit = self.page.locator('span:has-text("Submit"), button:has-text("Submit")').first
                if submit.is_visible():
                    submit.click()
                    time.sleep(0.5)
        except Exception as e:
            print(f"Failed to reject request: {e}")

    def get_daily_limits(self) -> Dict[str, Any]:
        """Navigate to daily limits section and return current limits."""
        try:
            limits_tab = self.page.locator('span:has-text("Daily Limits")').first
            if limits_tab.is_visible():
                limits_tab.click()
                self.page.wait_for_selector('input', timeout=5000)
                time.sleep(0.3)
                return {"visible": True}
        except Exception:
            pass
        return {"visible": False}

    def set_daily_limit(self, role: str, limit: int) -> None:
        """Set daily limit for a role."""
        try:
            input_field = self.page.locator(f'input[name="{role}_limit"]').first
            if input_field.is_visible():
                input_field.fill(str(limit))
                time.sleep(0.2)

                save_button = self.page.locator('span:has-text("Save"), button:has-text("Save")').first
                if save_button.is_visible():
                    save_button.click()
                    time.sleep(0.5)
        except Exception as e:
            print(f"Failed to set daily limit: {e}")

    def get_trash_items(self) -> int:
        """Navigate to trash and get item count."""
        try:
            trash_tab = self.page.locator('span:has-text("Trash")').first
            if trash_tab.is_visible():
                trash_tab.click()
                self.page.wait_for_selector('table', timeout=5000)
                rows = self.page.locators('table tbody tr').all()
                return len(rows)
        except Exception:
            pass
        return 0

    def restore_trash_item(self, item_idx: int) -> None:
        """Restore an item from trash."""
        try:
            row = self.page.locator(f'table tbody tr:nth-child({item_idx})').first
            restore_button = row.locator('span:has-text("Restore")').first
            if restore_button.is_visible():
                restore_button.click()
                time.sleep(0.5)
        except Exception as e:
            print(f"Failed to restore item: {e}")


class AuditPage(SplunkPage):
    """Audit dashboard page object."""

    def filter_by_action(self, action: str) -> None:
        """Filter audit events by action type."""
        try:
            filter_dropdown = self.page.locator('div[class*="action-filter"], select').first
            if filter_dropdown.is_visible():
                filter_dropdown.click()
                self.page.click(f'text="{action}"')
                self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception as e:
            print(f"Failed to filter audit by action: {e}")

    def get_event_count(self) -> int:
        """Get count of audit events displayed."""
        try:
            rows = self.page.locators('table tbody tr').all()
            return len(rows)
        except Exception:
            return 0

    def get_events_by_csv(self, csv_file: str) -> List[Dict[str, Any]]:
        """Get audit events for a specific CSV."""
        try:
            events = []
            rows = self.page.locators('table tbody tr').all()
            for row in rows:
                cells = row.locators('td').all()
                if cells and csv_file in cells[-1].text_content():
                    event_data = {
                        "csv": cells[-1].text_content() if cells else "",
                        "action": cells[0].text_content() if cells else "",
                    }
                    events.append(event_data)
            return events
        except Exception:
            return []
