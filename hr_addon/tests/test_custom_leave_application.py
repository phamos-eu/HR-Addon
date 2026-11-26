# Copyright (c) 2026, phamos.eu and Contributors
# See license.txt

from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from hrms.hr.doctype.leave_application.leave_application import InsufficientLeaveBalanceError

from hr_addon.overrides.custom_leave_application import (
	HrAddonLeaveApplication,
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

	def _leave_application(self):
		doc = HrAddonLeaveApplication.__new__(HrAddonLeaveApplication)
		doc.employee = "HR-EMP-00001"
		doc.leave_type = "Annual Leave"
		doc.from_date = "2026-12-24"
		doc.to_date = "2026-12-31"
		doc.half_day = 1
		doc.half_day_date = "2026-12-24"
		doc.status = "Open"
		doc.leave_balance = 4
		return doc

	# HRMS days are 4.5. After the second half-day holiday the request is 4, which matches the balance.
	@patch("hr_addon.overrides.custom_leave_application.frappe.db.get_single_value", return_value=2)
	@patch(
		"hrms.hr.doctype.leave_application.leave_application.is_lwp",
		return_value=False,
	)
	@patch(
		"hrms.hr.doctype.leave_application.leave_application.get_leave_balance_on",
		return_value={"leave_balance_for_consumption": 4},
	)
	@patch(
		"hrms.hr.doctype.leave_application.leave_application.get_number_of_leave_days",
		return_value=4.5,
	)
	@patch(
		"hr_addon.overrides.custom_leave_application.get_half_day_holiday_dates",
		return_value=[date(2026, 12, 24), date(2026, 12, 31)],
	)
	def test_exact_balance_allows_reduced_half_day_holiday_total(self, *args):
		doc = self._leave_application()
		doc.validate_balance_leaves()
		self.assertEqual(doc.total_leave_days, 4)

	# A request still above the balance after half-day holidays stays blocked.
	@patch(
		"hrms.hr.doctype.leave_application.leave_application.frappe.db.get_value",
		return_value=0,
	)
	@patch("hr_addon.overrides.custom_leave_application.frappe.db.get_single_value", return_value=2)
	@patch(
		"hrms.hr.doctype.leave_application.leave_application.is_lwp",
		return_value=False,
	)
	@patch(
		"hrms.hr.doctype.leave_application.leave_application.get_leave_balance_on",
		return_value={"leave_balance_for_consumption": 3},
	)
	@patch(
		"hrms.hr.doctype.leave_application.leave_application.get_number_of_leave_days",
		return_value=4.5,
	)
	@patch(
		"hr_addon.overrides.custom_leave_application.get_half_day_holiday_dates",
		return_value=[date(2026, 12, 24), date(2026, 12, 31)],
	)
	def test_balance_below_reduced_total_stays_blocked(self, *args):
		doc = self._leave_application()
		with self.assertRaises(InsufficientLeaveBalanceError):
			doc.validate_balance_leaves()

	# Used Leaves keeps the stored 4 when the ledger still has the one-half-day amount 4.5.
	@patch(
		"hr_addon.overrides.custom_leave_application.get_total_leave_days",
		return_value=4,
	)
	@patch(
		"hr_addon.overrides.custom_leave_application.frappe.db.get_value",
		return_value=frappe._dict(half_day=1, half_day_date="2026-12-24"),
	)
	@patch("hrms.hr.doctype.leave_application.leave_application.get_leave_entries")
	def test_used_leaves_uses_total_leave_days_for_a_fractional_ledger(self, mock_entries, _half, mock_days):
		from hrms.hr.doctype.leave_application.leave_application import get_leaves_for_period

		mock_entries.return_value = [
			frappe._dict(
				from_date=getdate("2026-12-24"),
				to_date=getdate("2026-12-31"),
				leaves=-4.5,
				transaction_name="HR-LAP-2026-00002",
				transaction_type="Leave Application",
				holiday_list="Annual Leave Half Day Test",
			)
		]
		self.assertEqual(
			get_leaves_for_period("HR-EMP-00003", "Annual Leave", "2026-01-01", "2026-12-31"),
			-4,
		)
		self.assertEqual(mock_days.call_args.args[4], 1)
		self.assertEqual(mock_days.call_args.args[5], "2026-12-24")

	# A whole ledger amount still passes Half Day Date, so 31.12 is not counted as a full day.
	@patch(
		"hr_addon.overrides.custom_leave_application.get_total_leave_days",
		return_value=4,
	)
	@patch(
		"hr_addon.overrides.custom_leave_application.frappe.db.get_value",
		return_value=frappe._dict(half_day=1, half_day_date="2026-12-24"),
	)
	@patch("hrms.hr.doctype.leave_application.leave_application.get_leave_entries")
	def test_used_leaves_keeps_half_day_when_ledger_is_a_whole_number(self, mock_entries, _half, _days):
		from hrms.hr.doctype.leave_application.leave_application import get_leaves_for_period

		mock_entries.return_value = [
			frappe._dict(
				from_date=getdate("2026-12-24"),
				to_date=getdate("2026-12-31"),
				leaves=-4,
				transaction_name="HR-LAP-2026-00002",
				transaction_type="Leave Application",
				holiday_list="Annual Leave Half Day Test",
			)
		]
		self.assertEqual(
			get_leaves_for_period("HR-EMP-00003", "Annual Leave", "2026-01-01", "2026-12-31"),
			-4,
		)

	# Carry-forward expiry writes the reduced total, not the single half-day count.
	@patch("hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry.create_leave_ledger_entry")
	@patch("erpnext.setup.doctype.employee.employee.get_holiday_list_for_employee", return_value="HL")
	@patch(
		"hr_addon.overrides.custom_leave_application.get_total_leave_days",
		return_value=4,
	)
	def test_carry_forward_expiry_ledger_uses_total_leave_days(self, _days, _holiday_list, mock_ledger):
		doc = self._leave_application()
		doc.create_ledger_entry_for_intermediate_allocation_expiry("2026-12-31", True, 0)
		self.assertEqual(mock_ledger.call_args.args[1]["leaves"], -4)

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
