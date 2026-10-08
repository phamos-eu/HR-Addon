# Copyright (c) 2026, phamos.eu and Contributors
# See license.txt

from datetime import date
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hr_addon.overrides.custom_leave_application import get_half_day_holiday_in_leave


class TestHalfDayHolidayInLeave(FrappeTestCase):
	# One Half Day Holiday in the leave range is returned so Leave Application can mark it half day.
	@patch(
		"hr_addon.overrides.custom_leave_application.frappe.get_all",
		return_value=[date(2026, 12, 24)],
	)
	def test_returns_the_single_half_day_holiday(self, _mock_get_all):
		self.assertEqual(
			get_half_day_holiday_in_leave("2026-12-23", "2026-12-25"),
			date(2026, 12, 24),
		)

	# Leave Application has only one half-day date, so two holidays are left for the user.
	@patch(
		"hr_addon.overrides.custom_leave_application.frappe.get_all",
		return_value=[date(2026, 12, 24), date(2026, 12, 31)],
	)
	def test_returns_none_when_more_than_one(self, _mock_get_all):
		self.assertIsNone(get_half_day_holiday_in_leave("2026-12-24", "2026-12-31"))

	# A date that is already a full holiday is not also marked as a half day.
	@patch(
		"hr_addon.overrides.custom_leave_application.get_holiday_dates_for_employee",
		return_value=["2026-12-24"],
	)
	@patch(
		"hr_addon.overrides.custom_leave_application.frappe.db.get_value",
		return_value=0,
	)
	@patch(
		"hr_addon.overrides.custom_leave_application.frappe.get_all",
		return_value=[date(2026, 12, 24)],
	)
	def test_skips_date_that_is_already_a_full_holiday(self, _mock_get_all, _mock_value, _mock_holidays):
		self.assertIsNone(
			get_half_day_holiday_in_leave(
				"2026-12-24", "2026-12-24", employee="HR-EMP-00001", leave_type="Casual Leave"
			)
		)
