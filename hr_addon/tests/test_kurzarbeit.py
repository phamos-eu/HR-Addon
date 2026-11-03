# Copyright (c) 2026, phamos.eu and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hr_addon.hr_addon.kurzarbeit import (
	apply_kurzarbeit_to_workday,
	kurzarbeit_submit_block_reason,
)


def _workday(**kwargs):
	doc = SimpleNamespace(
		employee="HR-EMP-00001",
		log_date="2026-10-05",
		status="Absent",
		target_hours=8,
		actual_working_hours=0,
		kurzarbeit_hours=0,
		employee_checkins=[],
	)
	for key, value in kwargs.items():
		setattr(doc, key, value)
	return doc


class TestKurzarbeit(FrappeTestCase):
	def test_short_day_with_checkins_is_topped_up_and_stays_present(self):
		doc = _workday(actual_working_hours=2, employee_checkins=[{"name": "IN"}])
		with patch(
			"hr_addon.hr_addon.kurzarbeit.get_approved_kurzarbeit_leave",
			return_value={"name": "HR-LAP-1", "leave_type": "Kurzarbeit"},
		):
			apply_kurzarbeit_to_workday(doc)
		self.assertEqual(doc.actual_working_hours, 8)
		self.assertEqual(doc.target_hours, 8)
		self.assertEqual(doc.kurzarbeit_hours, 6)
		self.assertEqual(doc.status, "Present")

	def test_day_without_checkins_becomes_full_hours_on_leave(self):
		doc = _workday(actual_working_hours=0, status="")
		with patch(
			"hr_addon.hr_addon.kurzarbeit.get_approved_kurzarbeit_leave",
			return_value={"name": "HR-LAP-1", "leave_type": "Kurzarbeit"},
		):
			apply_kurzarbeit_to_workday(doc)
		self.assertEqual(doc.actual_working_hours, 8)
		self.assertEqual(doc.kurzarbeit_hours, 8)
		self.assertEqual(doc.status, "On Leave")

	def test_overtime_day_is_not_reduced(self):
		doc = _workday(actual_working_hours=9, status="Present", employee_checkins=[{"name": "IN"}])
		with patch(
			"hr_addon.hr_addon.kurzarbeit.get_approved_kurzarbeit_leave",
			return_value={"name": "HR-LAP-1", "leave_type": "Kurzarbeit"},
		):
			apply_kurzarbeit_to_workday(doc)
		self.assertEqual(doc.actual_working_hours, 9)
		self.assertEqual(doc.kurzarbeit_hours, 0)
		self.assertEqual(doc.status, "Present")

	def test_exact_target_adds_nothing(self):
		doc = _workday(actual_working_hours=8, status="Present", employee_checkins=[{"name": "IN"}])
		with patch(
			"hr_addon.hr_addon.kurzarbeit.get_approved_kurzarbeit_leave",
			return_value={"name": "HR-LAP-1", "leave_type": "Kurzarbeit"},
		):
			apply_kurzarbeit_to_workday(doc)
		self.assertEqual(doc.actual_working_hours, 8)
		self.assertEqual(doc.kurzarbeit_hours, 0)

	def test_holiday_and_missing_checkin_are_left_unchanged(self):
		for status in ("Not Workday", "Missing Checkin"):
			doc = _workday(status=status, actual_working_hours=0)
			apply_kurzarbeit_to_workday(doc)
			self.assertEqual(doc.actual_working_hours, 0)
			self.assertEqual(doc.kurzarbeit_hours, 0)
			self.assertEqual(doc.status, status)

	def test_without_approved_leave_hours_stay_as_checked_in(self):
		doc = _workday(actual_working_hours=5, kurzarbeit_hours=3, status="Present")
		with patch(
			"hr_addon.hr_addon.kurzarbeit.get_approved_kurzarbeit_leave",
			return_value=None,
		):
			apply_kurzarbeit_to_workday(doc)
		self.assertEqual(doc.actual_working_hours, 5)
		self.assertEqual(doc.kurzarbeit_hours, 0)

	@patch("hr_addon.hr_addon.kurzarbeit.is_kurzarbeit_leave_type", return_value=True)
	@patch("hr_addon.hr_addon.kurzarbeit.today", return_value="2026-11-03")
	def test_submit_blocked_until_after_to_date(self, _today, _is_ka):
		future = SimpleNamespace(
			leave_type="Kurzarbeit", _action="submit", half_day=0, to_date="2026-11-03"
		)
		self.assertIn("after the To Date", kurzarbeit_submit_block_reason(future))
		past = SimpleNamespace(
			leave_type="Kurzarbeit", _action="submit", half_day=0, to_date="2026-11-02"
		)
		self.assertIsNone(kurzarbeit_submit_block_reason(past))

	@patch("hr_addon.hr_addon.kurzarbeit.is_kurzarbeit_leave_type", return_value=True)
	def test_half_day_is_blocked_on_submit(self, _is_ka):
		doc = SimpleNamespace(
			leave_type="Kurzarbeit", _action="submit", half_day=1, to_date="2026-10-31"
		)
		self.assertIn("Half Day", kurzarbeit_submit_block_reason(doc))

	@patch("hr_addon.hr_addon.kurzarbeit.is_kurzarbeit_leave_type", return_value=True)
	def test_draft_save_is_not_blocked(self, _is_ka):
		doc = SimpleNamespace(
			leave_type="Kurzarbeit", _action="save", half_day=0, to_date="2026-12-31"
		)
		self.assertIsNone(kurzarbeit_submit_block_reason(doc))
