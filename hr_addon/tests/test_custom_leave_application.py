# Copyright (c) 2026, phamos.eu and Contributors
# See license.txt

from datetime import date
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hr_addon.overrides.custom_leave_application import (
	get_first_half_day_holiday,
	reduce_leave_days_for_half_day_holidays,
)


class TestHalfDayHolidayLeaveDays(FrappeTestCase):
	# 24.12 and 31.12 are both half-day holidays: 5 working days become 4.
	@patch(
		"hr_addon.overrides.custom_leave_application.get_half_day_holiday_dates",
		return_value=[date(2026, 12, 24), date(2026, 12, 31)],
	)
	def test_two_half_day_holidays_reduce_five_days_to_four(self, _mock_dates):
		self.assertEqual(
			reduce_leave_days_for_half_day_holidays(
				5, "HR-EMP-00001", "Casual Leave", "2026-12-24", "2026-12-31"
			),
			4,
		)

	# A date the user already marked as half day is not reduced a second time.
	@patch(
		"hr_addon.overrides.custom_leave_application.get_half_day_holiday_dates",
		return_value=[date(2026, 12, 24), date(2026, 12, 31)],
	)
	def test_skips_date_already_marked_half_day(self, _mock_dates):
		self.assertEqual(
			reduce_leave_days_for_half_day_holidays(
				4.5,
				"HR-EMP-00001",
				"Casual Leave",
				"2026-12-24",
				"2026-12-31",
				half_day=1,
				half_day_date="2026-12-24",
			),
			4,
		)

	# Half Day Date is the earliest half-day holiday. Later ones stay in the day count only.
	@patch(
		"hr_addon.overrides.custom_leave_application.get_half_day_holiday_dates",
		return_value=[date(2026, 12, 24), date(2026, 12, 31)],
	)
	def test_first_half_day_holiday_is_the_earliest_date(self, _mock_dates):
		self.assertEqual(
			get_first_half_day_holiday("2026-12-24", "2026-12-31"),
			date(2026, 12, 24),
		)

	# No half-day holiday leaves the HRMS day count unchanged.
	@patch(
		"hr_addon.overrides.custom_leave_application.get_half_day_holiday_dates",
		return_value=[],
	)
	def test_no_half_day_holiday_keeps_original_days(self, _mock_dates):
		self.assertEqual(
			reduce_leave_days_for_half_day_holidays(
				5, "HR-EMP-00001", "Casual Leave", "2026-12-24", "2026-12-31"
			),
			5,
		)
