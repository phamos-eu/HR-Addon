# Copyright (c) 2026, Akhilaminc and Contributors
# See license.txt
"""Tests for Overtime Payout submit/cancel and resulting Overtime Ledger entries."""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate
from erpnext.setup.doctype.employee.test_employee import make_employee

from hr_addon.events.overtime_ledger import get_employee_overtime_balance


def _overtime_payout_naming_series():
	field = frappe.get_meta("Overtime Payout").get_field("naming_series")
	if not field or not field.options:
		return None
	for line in field.options.split("\n"):
		s = line.strip()
		if s:
			return s
	return None


class TestOvertimePayout(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		frappe.flags.in_import = True
		super().setUpClass()

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		frappe.flags.in_import = False

	def tearDown(self):
		frappe.db.rollback()

	def _set_frozen_past(self):
		doc = frappe.get_single("HR Addon Settings")
		doc.overtime_frozen = add_days(getdate(), -180)
		doc.enable_overtime_ledger_feature = 1
		doc.save()

	def _submit_payout(self, employee, posting_date, purpose, hours_seconds):
		"""Create and submit Overtime Payout with given Duration (seconds); returns payout doc."""
		series = _overtime_payout_naming_series()
		if not series:
			self.skipTest("Overtime Payout has no naming series options on this site")
		payout = frappe.get_doc(
			{
				"doctype": "Overtime Payout",
				"naming_series": series,
				"employee": employee,
				"posting_date": posting_date,
				"posting_time": "11:00:00",
				"purpose": purpose,
				"hours": hours_seconds,
				"company": "_Test Company",
			}
		)
		payout.flags.ignore_permissions = True
		payout.insert()
		payout.submit()
		return payout

	def _assert_active_ole_for_payout(self, payout_name):
		row = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Overtime Payout",
				"voucher_no": payout_name,
				"is_cancelled": 0,
			},
			["name", "hour_variance", "balance_before", "balance_after"],
			as_dict=True,
		)
		self.assertTrue(row and row.name)
		return row

	def test_overtime_payout_submit_creates_active_ole_positive_adjustment(self):
		"""Positive Adjustment payout increases overtime balance → OLE hour_variance positive (hours as Duration seconds)."""
		self._set_frozen_past()
		posting_date = add_days(getdate(), 3)
		employee = make_employee(
			f"ole_payout_pos_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		payout = self._submit_payout(employee, posting_date, "Positive Adjustment", 3600)
		ole = self._assert_active_ole_for_payout(payout.name)
		self.assertAlmostEqual(flt(ole.hour_variance), 1.0, places=2)
		self.assertGreater(flt(ole.hour_variance), 0)

	def test_overtime_payout_pay_out_creates_negative_ole(self):
		"""Pay-out reduces accrued overtime → OLE hour_variance negative matching payout hours."""
		self._set_frozen_past()
		posting_date = add_days(getdate(), 5)
		employee = make_employee(
			f"ole_payout_out_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		payout = self._submit_payout(employee, posting_date, "Pay-out", 7200)
		ole = self._assert_active_ole_for_payout(payout.name)
		self.assertAlmostEqual(flt(ole.hour_variance), -2.0, places=2)
		self.assertLess(flt(ole.hour_variance), 0)

	def test_overtime_payout_negative_adjustment_creates_negative_ole(self):
		"""Negative Adjustment subtracts overtime like Pay-out → OLE hour_variance negative."""
		self._set_frozen_past()
		posting_date = add_days(getdate(), 6)
		employee = make_employee(
			f"ole_payout_negadj_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		payout = self._submit_payout(
			employee, posting_date, "Negative Adjustment", int(3600 + 3600 / 4)
		)
		ole = self._assert_active_ole_for_payout(payout.name)
		self.assertAlmostEqual(flt(ole.hour_variance), -1.25, places=2)
		self.assertLess(flt(ole.hour_variance), 0)

	def test_overtime_payout_cancel_marks_original_ole_cancelled(self):
		"""Cancelling payout creates reversal OLE, cancels original, restores employee balance."""
		self._set_frozen_past()
		# Past date so payout OLE posting_datetime is always <= now for balance API.
		posting_date = add_days(getdate(), -1)
		employee = make_employee(
			f"ole_payout_cancel_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		balance_before = flt(get_employee_overtime_balance(employee).get("balance"))
		payout = self._submit_payout(employee, posting_date, "Positive Adjustment", 3600)

		ole_name = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Overtime Payout",
				"voucher_no": payout.name,
				"is_cancelled": 0,
			},
			"name",
		)
		self.assertTrue(ole_name)
		original_hv = flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance"))
		self.assertAlmostEqual(
			flt(get_employee_overtime_balance(employee).get("balance")),
			balance_before + original_hv,
			places=4,
		)

		payout.flags.ignore_permissions = True
		payout.cancel()

		self.assertEqual(
			frappe.db.get_value("Overtime Ledger Entry", ole_name, "is_cancelled"),
			1,
		)
		reversals = frappe.get_all(
			"Overtime Ledger Entry",
			filters={
				"voucher_type": "Overtime Payout",
				"voucher_no": payout.name,
				"is_cancelled": 0,
			},
			fields=["hour_variance", "remarks"],
		)
		self.assertEqual(len(reversals), 1)
		self.assertAlmostEqual(flt(reversals[0].hour_variance), -original_hv, places=4)
		self.assertAlmostEqual(
			flt(get_employee_overtime_balance(employee).get("balance")),
			balance_before,
			places=4,
		)
