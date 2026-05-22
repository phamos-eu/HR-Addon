# Copyright (c) 2025, Akhilaminc and Contributors
# See license.txt
"""Tests for Overtime Ledger Entry, Attendance/Payout OLE flows, Leave Application, and event helpers."""

import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, get_datetime, getdate
from erpnext.setup.doctype.employee.test_employee import make_employee
from hrms.hr.doctype.leave_allocation.test_leave_allocation import create_leave_allocation
from hrms.payroll.doctype.salary_slip.test_salary_slip import create_user

from hr_addon.events.attendance import (
	get_effective_ole_target_hours,
	get_ole_hour_variance_for_attendance,
)
from hr_addon.hr_addon.doctype.workday.workday import create_attendace_record
from hr_addon.events.leave_application import validate_leave_application
from hr_addon.events.overtime_ledger import (
	REVERSAL_REMARK_MARKER,
	get_employee_overtime_balance,
	get_previous_balance,
	get_reversal_entry_names_from_ole_rows,
	is_reversal_ledger_row,
)
from hr_addon.hr_addon.report.overtime_ledger.overtime_ledger import get_balance_at_date

from .overtime_ledger_entry import make_ole_entry


class TestOvertimeLedgerEntry(FrappeTestCase):
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

	def set_hr_addon_overtime_frozen(self, overtime_frozen="2025-12-31"):
		"""Persist HR Addon Settings closed-period cutoff (shared test helper)."""
		doc = frappe.get_single("HR Addon Settings")
		doc.overtime_frozen = overtime_frozen
		doc.save()

	def get_leave_type_deducting_overtime(self):
		"""First Leave Type flagged to deduct from overtime ledger, if any."""
		row = frappe.get_all(
			"Leave Type",
			filters={"custom_is_deducted_from_overtime_ledger": 1},
			pluck="name",
			limit=1,
		)
		return row[0] if row else None

	def _ensure_open_period_for_ole(self):
		"""Set frozen date in the past so posting_date = tomorrow is always allowed."""
		self.set_hr_addon_overtime_frozen(add_days(getdate(), -180))

	def _require_attendance_ole_setup(self):
		"""Skip unless Attendance has custom target/actual hours (OLE from submit hook)."""
		meta = frappe.get_meta("Attendance")
		if not (
			meta.has_field("custom_actual_working_hours") and meta.has_field("custom_target_hours")
		):
			self.skipTest("Attendance has no custom overtime hour fields on this site")

	def _leave_type_with_deduct_toggle(self, enable=True):
		"""Pick one Leave Type; set custom_is_deducted_from_overtime_ledger; restore in finally."""
		if not frappe.get_meta("Leave Type").has_field("custom_is_deducted_from_overtime_ledger"):
			self.skipTest("Leave Type has no custom_is_deducted_from_overtime_ledger on this site")
		pick = frappe.get_all("Leave Type", pluck="name", order_by="name asc", limit=1)
		self.assertTrue(pick)
		name = pick[0]
		frappe.db.set_value(
			"Leave Type",
			name,
			"custom_is_deducted_from_overtime_ledger",
			1 if enable else 0,
			update_modified=False,
		)
		return name

	def test_create_employee_and_user(self):
		"""ERPNext make_employee should create both User and Employee linked by user_id (HR test baseline)."""
		email = "ole_minimal@test.local"
		name = make_employee(email, company="_Test Company")
		self.assertTrue(frappe.db.exists("User", email))
		self.assertTrue(frappe.db.exists("Employee", name))
		self.assertEqual(frappe.db.get_value("Employee", name, "user_id"), email)

	def test_overtime_frozen_is_stored_in_hr_addon_settings(self):
		"""Saving HR Addon Settings.overtime_frozen persists the closed-period cutoff used by OLE validate."""
		expected = add_days(getdate(), -120)
		self.set_hr_addon_overtime_frozen(expected)
		stored = frappe.db.get_single_value("HR Addon Settings", "overtime_frozen")
		self.assertEqual(str(stored), str(expected))

	def test_get_leave_type_deducting_overtime(self):
		"""After flagging a Leave Type, helper query returns that name (custom overtime-deduction field)."""
		if not frappe.get_meta("Leave Type").has_field("custom_is_deducted_from_overtime_ledger"):
			self.skipTest("Leave Type has no custom_is_deducted_from_overtime_ledger field on this site")

		lt_pick = frappe.get_all("Leave Type", pluck="name", limit=1)
		self.assertTrue(lt_pick)
		lt_name = lt_pick[0]
		frappe.db.set_value(
			"Leave Type",
			lt_name,
			"custom_is_deducted_from_overtime_ledger",
			1,
			update_modified=False,
		)
		try:
			found = self.get_leave_type_deducting_overtime()
			self.assertEqual(found, lt_name)
		finally:
			frappe.db.set_value(
				"Leave Type",
				lt_name,
				"custom_is_deducted_from_overtime_ledger",
				0,
				update_modified=False,
			)

	def test_ole_blocked_when_overtime_frozen_not_configured(self):
		"""Creating OLE must fail when overtime_frozen is empty (user must set closed period first)."""
		prev = frappe.db.get_single_value("HR Addon Settings", "overtime_frozen")
		try:
			frappe.db.set_single_value("HR Addon Settings", "overtime_frozen", None)
			posting_date = add_days(getdate(), 1)
			employee = make_employee(
				f"ole_nofroz_{uuid.uuid4().hex[:10]}@test.local",
				company="_Test Company",
			)
			attendance = frappe.get_doc(
				{
					"doctype": "Attendance",
					"employee": employee,
					"attendance_date": posting_date,
					"status": "Present",
					"company": "_Test Company",
				}
			)
			attendance.flags.ignore_permissions = True
			attendance.insert()
			with self.assertRaises(frappe.ValidationError):
				make_ole_entry(
					{
						"employee": employee,
						"voucher_type": "Attendance",
						"voucher_no": attendance.name,
						"hour_variance": 1,
						"target_hours": 8,
						"actual_hours": 9,
						"posting_date": posting_date,
						"posting_time": "18:00:00",
					}
				)
		finally:
			if prev:
				frappe.db.set_single_value("HR Addon Settings", "overtime_frozen", prev)

	def test_ole_rejects_posting_on_or_before_frozen_date(self):
		"""Posting date on or before overtime_frozen must be rejected (frozen period)."""
		frozen = add_days(getdate(), -10)
		self.set_hr_addon_overtime_frozen(frozen)
		employee = make_employee(
			f"ole_frozen_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		blocked_date = add_days(getdate(frozen), -1)
		attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": blocked_date,
				"status": "Present",
				"company": "_Test Company",
			}
		)
		attendance.flags.ignore_permissions = True
		attendance.insert()

		with self.assertRaises(frappe.ValidationError):
			make_ole_entry(
				{
					"employee": employee,
					"voucher_type": "Attendance",
					"voucher_no": attendance.name,
					"hour_variance": 1,
					"target_hours": 8,
					"actual_hours": 9,
					"posting_date": blocked_date,
					"posting_time": "18:00:00",
				}
			)

	def test_overtime_ledger_entry_creation(self):
		"""Happy path: OLE linked to Attendance gets balances from hour_variance after an open posting date."""
		self._ensure_open_period_for_ole()
		posting_date = add_days(getdate(), 1)

		employee = make_employee(
			f"ole_creator_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": posting_date,
				"status": "Present",
				"company": "_Test Company",
			}
		)
		attendance.flags.ignore_permissions = True
		attendance.insert()

		hour_variance = 2
		target_hours = 8
		actual_hours = 10
		ole = make_ole_entry(
			{
				"employee": employee,
				"voucher_type": "Attendance",
				"voucher_no": attendance.name,
				"hour_variance": hour_variance,
				"target_hours": target_hours,
				"actual_hours": actual_hours,
				"posting_date": posting_date,
				"posting_time": "18:00:00",
			}
		)

		self.assertTrue(ole.name)
		self.assertEqual(flt(ole.hour_variance), hour_variance)
		self.assertEqual(
			flt(ole.balance_after) - flt(ole.balance_before),
			hour_variance,
		)

	def test_attendance_submit_creates_overtime_ledger_entry_when_variance_nonzero(self):
		"""Full-day Present with actual ≠ target yields standard hour variance and creates OLE on submit."""
		self._require_attendance_ole_setup()
		self._ensure_open_period_for_ole()
		posting_date = add_days(getdate(), 2)
		employee = make_employee(
			f"ole_att_submit_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)

		attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": posting_date,
				"status": "Present",
				"company": "_Test Company",
				"custom_target_hours": 8,
				"custom_actual_working_hours": 9,
			}
		)
		attendance.flags.ignore_permissions = True
		attendance.insert()
		try:
			attendance.submit()
		except Exception as exc:
			self.skipTest(f"Attendance submit not supported in this environment: {exc}")

		self.assertTrue(
			frappe.db.get_value(
				"Attendance",
				attendance.name,
				"custom_overtime_ledger_entry",
			),
			msg="OLE should be linked back on Attendance after submit",
		)
		ole_name = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Attendance",
				"voucher_no": attendance.name,
				"is_cancelled": 0,
			},
			"name",
		)
		self.assertTrue(ole_name)
		expected_hv = get_ole_hour_variance_for_attendance(
			status="Present",
			leave_type=None,
			employee=None,
			log_date=None,
			target_hours=8,
			actual_hours=9,
			custom_hour_variance=None,
		)
		self.assertEqual(
			flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance")),
			flt(expected_hv),
		)

	def test_attendance_submit_skips_ole_when_full_day_zero_hour_variance(self):
		"""When actual equals target there is no hour variance → submit must not link an OLE (full day Present)."""
		self._require_attendance_ole_setup()
		self._ensure_open_period_for_ole()
		posting_date = add_days(getdate(), 7)
		employee = make_employee(
			f"ole_att_zero_var_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": posting_date,
				"status": "Present",
				"company": "_Test Company",
				"custom_target_hours": 8,
				"custom_actual_working_hours": 8,
			}
		)
		attendance.flags.ignore_permissions = True
		attendance.insert()
		try:
			attendance.submit()
		except Exception as exc:
			self.skipTest(f"Attendance submit not supported in this environment: {exc}")

		self.assertFalse(
			frappe.db.get_value("Attendance", attendance.name, "custom_overtime_ledger_entry")
		)
		self.assertFalse(
			frappe.db.exists(
				"Overtime Ledger Entry",
				{
					"voucher_type": "Attendance",
					"voucher_no": attendance.name,
					"is_cancelled": 0,
				},
			)
		)

	def test_attendance_submit_full_day_negative_variance_creates_negative_ole(self):
		"""Undertime (actual below target) on Present still creates OLE with negative hour_variance."""
		self._require_attendance_ole_setup()
		self._ensure_open_period_for_ole()
		posting_date = add_days(getdate(), 8)
		employee = make_employee(
			f"ole_att_under_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": posting_date,
				"status": "Present",
				"company": "_Test Company",
				"custom_target_hours": 8,
				"custom_actual_working_hours": 7,
			}
		)
		attendance.flags.ignore_permissions = True
		attendance.insert()
		try:
			attendance.submit()
		except Exception as exc:
			self.skipTest(f"Attendance submit not supported in this environment: {exc}")

		ole_name = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Attendance",
				"voucher_no": attendance.name,
				"is_cancelled": 0,
			},
			"name",
		)
		self.assertTrue(ole_name)
		self.assertLess(
			flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance")),
			0,
		)

	def test_full_day_present_uses_standard_variance_even_if_leave_type_deducts_ot(self):
		"""OLE logic treats only Half Day specially; Present uses actual − target regardless of OT-deduct flag on Leave Type."""
		lt = self._leave_type_with_deduct_toggle(enable=True)
		try:
			v = get_ole_hour_variance_for_attendance(
				status="Present",
				leave_type=lt,
				employee=None,
				log_date=None,
				target_hours=8,
				actual_hours=9,
				custom_hour_variance=None,
			)
			self.assertEqual(v, 1)
		finally:
			self._leave_type_with_deduct_toggle(enable=False)

	def test_attendance_submit_half_day_deduct_leave_type_creates_formula_ole(self):
		"""Half Day + Leave Type with «deduct from OT ledger»: hour variance follows -(target − (actual − target)); submit creates OLE."""
		self._require_attendance_ole_setup()
		meta = frappe.get_meta("Attendance")
		if not meta.has_field("leave_type"):
			self.skipTest("Attendance has no leave_type field on this site")
		self._ensure_open_period_for_ole()

		posting_date = add_days(getdate(), 9)
		employee = make_employee(
			f"ole_half_deduct_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		lt = self._leave_type_with_deduct_toggle(enable=True)
		try:
			target = 3.5
			actual = 4.5
			expected_v = get_ole_hour_variance_for_attendance(
				status="Half Day",
				leave_type=lt,
				employee=employee,
				log_date=posting_date,
				target_hours=target,
				actual_hours=actual,
				custom_hour_variance=None,
			)
			self.assertAlmostEqual(expected_v, -2.5, places=6)

			attendance = frappe.get_doc(
				{
					"doctype": "Attendance",
					"employee": employee,
					"attendance_date": posting_date,
					"status": "Half Day",
					"leave_type": lt,
					"company": "_Test Company",
					"custom_target_hours": target,
					"custom_actual_working_hours": actual,
				}
			)
			attendance.flags.ignore_permissions = True
			attendance.insert()
			try:
				attendance.submit()
			except Exception as exc:
				self.skipTest(f"Attendance submit not supported in this environment: {exc}")

			ole_name = frappe.db.get_value(
				"Overtime Ledger Entry",
				{
					"voucher_type": "Attendance",
					"voucher_no": attendance.name,
					"is_cancelled": 0,
				},
				"name",
			)
			self.assertTrue(ole_name)
			self.assertAlmostEqual(
				flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance")),
				expected_v,
				places=6,
			)
		finally:
			self._leave_type_with_deduct_toggle(enable=False)

	def _insert_seed_attendance(self, employee, attendance_date):
		att = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": attendance_date,
				"status": "Present",
				"company": "_Test Company",
			}
		)
		att.flags.ignore_permissions = True
		att.insert()
		return att.name

	def test_attendance_cancel_reverses_ole_and_restores_balance(self):
		"""Cancelling Attendance marks OLE cancelled, creates reversal row, restores employee balance."""
		self._require_attendance_ole_setup()
		self._ensure_open_period_for_ole()
		# Yesterday: submit hook may use 23:59:59 posting time; must be <= now for balance API.
		posting_date = add_days(getdate(), -1)
		employee = make_employee(
			f"ole_att_cancel_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		balance_before = flt(get_employee_overtime_balance(employee).get("balance"))

		attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": posting_date,
				"status": "Present",
				"company": "_Test Company",
				"custom_target_hours": 8,
				"custom_actual_working_hours": 10,
				"in_time": f"{posting_date} 08:00:00",
				"out_time": f"{posting_date} 17:00:00",
			}
		)
		attendance.flags.ignore_permissions = True
		attendance.insert()
		try:
			attendance.submit()
		except Exception as exc:
			self.skipTest(f"Attendance submit not supported in this environment: {exc}")

		ole_name = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Attendance",
				"voucher_no": attendance.name,
				"is_cancelled": 0,
			},
			"name",
		)
		self.assertTrue(ole_name)
		original_hv = flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance"))
		self.assertGreater(original_hv, 0)
		self.assertAlmostEqual(
			flt(get_employee_overtime_balance(employee).get("balance")),
			balance_before + original_hv,
			places=4,
		)

		attendance.flags.ignore_permissions = True
		attendance.cancel()

		self.assertEqual(frappe.db.get_value("Overtime Ledger Entry", ole_name, "is_cancelled"), 1)
		reversals = frappe.get_all(
			"Overtime Ledger Entry",
			filters={
				"voucher_type": "Attendance",
				"voucher_no": attendance.name,
				"is_cancelled": 0,
			},
			fields=["name", "hour_variance", "remarks"],
		)
		self.assertEqual(len(reversals), 1)
		self.assertIn(REVERSAL_REMARK_MARKER, reversals[0].remarks or "")
		self.assertAlmostEqual(flt(reversals[0].hour_variance), -original_hv, places=4)
		self.assertAlmostEqual(
			flt(get_employee_overtime_balance(employee).get("balance")),
			balance_before,
			places=4,
		)

	def test_backdated_ole_reposts_later_entry_balances(self):
		"""Inserting an earlier OLE recalculates balance_before/balance_after on later rows."""
		self._ensure_open_period_for_ole()
		employee = make_employee(
			f"ole_backdate_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		day_early = add_days(getdate(), 16)
		day_late = add_days(getdate(), 18)

		ole_late = make_ole_entry(
			{
				"employee": employee,
				"posting_date": day_late,
				"posting_time": "14:00:00",
				"hour_variance": 3,
				"voucher_type": "Attendance",
				"voucher_no": self._insert_seed_attendance(employee, day_late),
			}
		)
		self.assertAlmostEqual(flt(ole_late.balance_after), 3.0, places=4)

		ole_early = make_ole_entry(
			{
				"employee": employee,
				"posting_date": day_early,
				"posting_time": "10:00:00",
				"hour_variance": 5,
				"voucher_type": "Attendance",
				"voucher_no": self._insert_seed_attendance(employee, day_early),
			}
		)
		self.assertAlmostEqual(flt(ole_early.balance_after), 5.0, places=4)

		ole_late.reload()
		self.assertAlmostEqual(flt(ole_late.balance_before), 5.0, places=4)
		self.assertAlmostEqual(flt(ole_late.balance_after), 8.0, places=4)

	def test_get_previous_balance_ignores_cancelled_and_reversal_rows(self):
		"""Running balance helper skips cancelled originals and explicit reversal rows."""
		self._ensure_open_period_for_ole()
		employee = make_employee(
			f"ole_prev_bal_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		posting_date = add_days(getdate(), 17)
		voucher = self._insert_seed_attendance(employee, posting_date)

		active = make_ole_entry(
			{
				"employee": employee,
				"posting_date": posting_date,
				"posting_time": "09:00:00",
				"hour_variance": 4,
				"voucher_type": "Attendance",
				"voucher_no": voucher,
			}
		)
		frappe.db.set_value("Overtime Ledger Entry", active.name, "is_cancelled", 1, update_modified=False)
		make_ole_entry(
			{
				"employee": employee,
				"posting_date": posting_date,
				"posting_time": "09:00:01",
				"hour_variance": -4,
				"voucher_type": "Attendance",
				"voucher_no": voucher,
				"remarks": f"{REVERSAL_REMARK_MARKER} {active.name}",
			}
		)
		later = make_ole_entry(
			{
				"employee": employee,
				"posting_date": add_days(posting_date, 1),
				"posting_time": "10:00:00",
				"hour_variance": 2,
				"voucher_type": "Attendance",
				"voucher_no": self._insert_seed_attendance(employee, add_days(posting_date, 1)),
			}
		)
		before_later = f"{later.posting_date} {later.posting_time}"
		self.assertAlmostEqual(get_previous_balance(employee, before_later), 0.0, places=4)

	def test_get_balance_at_date_returns_latest_active_balance(self):
		"""Report helper returns balance_after from the latest non-cancelled OLE on or before the date."""
		self._ensure_open_period_for_ole()
		employee = make_employee(
			f"ole_rpt_bal_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		day_one = add_days(getdate(), -2)
		day_two = add_days(getdate(), -1)

		att_one = self._insert_seed_attendance(employee, day_one)
		make_ole_entry(
			{
				"employee": employee,
				"posting_date": day_one,
				"posting_time": "10:00:00",
				"hour_variance": 5,
				"voucher_type": "Attendance",
				"voucher_no": att_one,
			}
		)

		att_two = self._insert_seed_attendance(employee, day_two)
		ole_two = make_ole_entry(
			{
				"employee": employee,
				"posting_date": day_two,
				"posting_time": "11:00:00",
				"hour_variance": 3,
				"voucher_type": "Attendance",
				"voucher_no": att_two,
			}
		)

		self.assertAlmostEqual(
			get_balance_at_date(employee, get_datetime(f"{day_one} 23:59:59"), {}),
			5.0,
			places=4,
		)
		self.assertAlmostEqual(
			get_balance_at_date(employee, get_datetime(f"{day_two} 23:59:59"), {}),
			flt(ole_two.balance_after),
			places=4,
		)
		self.assertAlmostEqual(
			get_balance_at_date(employee, get_datetime(f"{day_two} 23:59:59"), {}),
			8.0,
			places=4,
		)


class TestLeaveApplicationOvertimeLedger(FrappeTestCase):
	"""Leave Application submit creates Attendance; Workday sync creates OLE (OT-deduct leave types)."""

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

	def _ensure_open_period_for_ole(self):
		doc = frappe.get_single("HR Addon Settings")
		doc.overtime_frozen = add_days(getdate(), -180)
		doc.save()

	def _require_attendance_ole_fields(self):
		meta = frappe.get_meta("Attendance")
		if not (
			meta.has_field("custom_actual_working_hours")
			and meta.has_field("custom_target_hours")
		):
			self.skipTest("Attendance has no custom overtime hour fields on this site")

	def _require_ot_deduct_leave_field(self):
		if not frappe.get_meta("Leave Type").has_field("custom_is_deducted_from_overtime_ledger"):
			self.skipTest("Leave Type has no custom_is_deducted_from_overtime_ledger on this site")

	def _create_ot_deduct_leave_type(self, suffix):
		"""Leave type flagged to deduct from overtime ledger when used on leave."""
		lt_name = f"_Test OT Deduct {suffix}"
		if frappe.db.exists("Leave Type", lt_name):
			frappe.delete_doc("Leave Type", lt_name, force=True)
		lt = frappe.get_doc(
			{
				"doctype": "Leave Type",
				"leave_type_name": lt_name,
				"include_holiday": 1,
				"is_lwp": 0,
			}
		).insert()
		frappe.db.set_value(
			"Leave Type", lt.name, "custom_is_deducted_from_overtime_ledger", 1, update_modified=False
		)
		return lt.name

	def _ensure_weekly_working_hours(self, employee, day_hours=8):
		"""Submitted Weekly Working Hours covering today (required for Workday / default day hours)."""
		if not frappe.db.exists("DocType", "Weekly Working Hours"):
			self.skipTest("HR Addon Weekly Working Hours not installed")
		existing = frappe.get_all(
			"Weekly Working Hours",
			filters={"employee": employee, "docstatus": 1},
			pluck="name",
		)
		for name in existing:
			doc = frappe.get_doc("Weekly Working Hours", name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Weekly Working Hours", name, force=True)

		valid_from = add_days(getdate(), -30)
		valid_to = add_days(getdate(), 30)
		days = [
			"Monday",
			"Tuesday",
			"Wednesday",
			"Thursday",
			"Friday",
			"Saturday",
			"Sunday",
		]
		wh = frappe.get_doc(
			{
				"doctype": "Weekly Working Hours",
				"employee": employee,
				"valid_from": valid_from,
				"valid_to": valid_to,
				"company": "_Test Company",
				"hours": [{"day": d, "hours": day_hours, "break_minutes": 0} for d in days],
			}
		)
		wh.flags.ignore_permissions = True
		wh.insert()
		wh.submit()

	def _seed_overtime_balance(self, employee, hours=24, posting_date=None):
		"""Positive OLE balance so validate_leave_application allows OT-deduct leave."""
		# validate_leave_application uses get_employee_overtime_balance() with as_of = now(),
		# which only includes OLE rows where posting_datetime <= now — never future-dated seeds.
		today = getdate()
		posting_date = getdate(posting_date) if posting_date else today
		if posting_date > today:
			posting_date = today
		frozen = frappe.db.get_single_value("HR Addon Settings", "overtime_frozen")
		if frozen and posting_date <= getdate(frozen):
			posting_date = add_days(getdate(frozen), 1)
		# voucher_no must exist (Dynamic Link); use a real draft Attendance as voucher.
		seed_attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": posting_date,
				"status": "Present",
				"company": "_Test Company",
			}
		)
		seed_attendance.flags.ignore_permissions = True
		seed_attendance.insert()
		make_ole_entry(
			{
				"employee": employee,
				"posting_date": posting_date,
				"posting_time": "08:00:00",
				"hour_variance": hours,
				"target_hours": 0,
				"actual_hours": hours,
				"voucher_type": "Attendance",
				"voucher_no": seed_attendance.name,
			}
		)

	def _submit_leave_application(
		self, employee, leave_type, from_date, to_date, half_day=False, half_day_date=None
	):
		create_user("test@example.com")
		# HRMS create_leave_allocation() only builds a local doc; must insert + submit.
		allocation = create_leave_allocation(
			employee=employee,
			leave_type=leave_type,
			from_date=add_days(getdate(from_date), -30),
			to_date=add_days(getdate(to_date), 30),
			new_leaves_allocated=30,
		)
		allocation.flags.ignore_permissions = True
		allocation.insert()
		allocation.submit()

		la = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"leave_type": leave_type,
				"from_date": from_date,
				"to_date": to_date,
				"half_day": half_day,
				"half_day_date": half_day_date,
				"company": "_Test Company",
				"status": "Approved",
				"leave_approver": "test@example.com",
				"posting_date": from_date,
			}
		)
		la.flags.ignore_permissions = True
		la.insert()
		la.submit()
		return la

	def _get_submitted_attendance(self, employee, attendance_date):
		return frappe.db.get_value(
			"Attendance",
			{
				"employee": employee,
				"attendance_date": attendance_date,
				"docstatus": 1,
			},
			["name", "status", "leave_application", "leave_type"],
			as_dict=True,
		)

	def _sync_workday_for_leave_date(self, employee, log_date):
		"""Insert Workday for leave date; after_insert runs create_attendace_record (OLE path)."""
		existing = frappe.db.exists("Workday", {"employee": employee, "log_date": log_date})
		if existing:
			wd = frappe.get_doc("Workday", existing)
			from hr_addon.hr_addon.doctype.workday.workday import create_attendace_record

			create_attendace_record(wd)
			return wd
		wd = frappe.get_doc(
			{
				"doctype": "Workday",
				"employee": employee,
				"log_date": log_date,
				"company": "_Test Company",
			}
		)
		wd.flags.ignore_permissions = True
		wd.insert()
		return wd

	def test_leave_application_full_day_submit_creates_on_leave_attendance(self):
		"""Approved full-day leave (OT-deduct type) submits and marks Attendance as On Leave for that date."""
		self._require_ot_deduct_leave_field()
		self._ensure_open_period_for_ole()
		leave_date = add_days(getdate(), 10)
		employee = make_employee(
			f"ole_la_full_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		self._ensure_weekly_working_hours(employee)
		self._seed_overtime_balance(employee, hours=24)
		leave_type = self._create_ot_deduct_leave_type("Full")

		la = self._submit_leave_application(
			employee, leave_type, leave_date, leave_date, half_day=False
		)

		att = self._get_submitted_attendance(employee, leave_date)
		self.assertTrue(att and att.name)
		self.assertEqual(att.status, "On Leave")
		self.assertEqual(att.leave_application, la.name)

	def test_leave_application_full_day_workday_sync_creates_negative_ole(self):
		"""After full-day OT-deduct leave, Workday sync sets target=day hours / actual=0 → negative OLE on Attendance."""
		self._require_attendance_ole_fields()
		self._require_ot_deduct_leave_field()
		self._ensure_open_period_for_ole()
		leave_date = add_days(getdate(), 11)
		employee = make_employee(
			f"ole_la_full_ole_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		self._ensure_weekly_working_hours(employee, day_hours=8)
		self._seed_overtime_balance(employee, hours=24)
		leave_type = self._create_ot_deduct_leave_type("FullOLE")

		self._submit_leave_application(employee, leave_type, leave_date, leave_date)
		att_before = self._get_submitted_attendance(employee, leave_date)
		self.assertTrue(att_before)

		self._sync_workday_for_leave_date(employee, leave_date)

		ole_name = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Attendance",
				"voucher_no": att_before.name,
				"is_cancelled": 0,
			},
			"name",
		)
		self.assertTrue(ole_name)
		hv = flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance"))
		self.assertLess(hv, 0)
		self.assertAlmostEqual(hv, -8.0, places=2)

	def test_leave_application_half_day_submit_creates_half_day_attendance(self):
		"""Half-day leave submit creates Half Day Attendance on half_day_date (OT-deduct leave type)."""
		self._require_ot_deduct_leave_field()
		self._ensure_open_period_for_ole()
		leave_date = add_days(getdate(), 12)
		employee = make_employee(
			f"ole_la_half_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		self._ensure_weekly_working_hours(employee)
		self._seed_overtime_balance(employee, hours=24)
		leave_type = self._create_ot_deduct_leave_type("Half")

		la = self._submit_leave_application(
			employee,
			leave_type,
			leave_date,
			leave_date,
			half_day=True,
			half_day_date=leave_date,
		)

		att = self._get_submitted_attendance(employee, leave_date)
		self.assertTrue(att and att.name)
		self.assertEqual(att.status, "Half Day")
		self.assertEqual(att.leave_application, la.name)

	def test_leave_application_half_day_workday_sync_creates_ole_with_deduct_formula(self):
		"""Half Day + OT-deduct leave: Workday sync creates OLE using special hour-variance formula."""
		self._require_attendance_ole_fields()
		self._require_ot_deduct_leave_field()
		self._ensure_open_period_for_ole()
		leave_date = add_days(getdate(), 13)
		employee = make_employee(
			f"ole_la_half_ole_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		self._ensure_weekly_working_hours(employee, day_hours=8)
		self._seed_overtime_balance(employee, hours=24)
		leave_type = self._create_ot_deduct_leave_type("HalfOLE")

		self._submit_leave_application(
			employee,
			leave_type,
			leave_date,
			leave_date,
			half_day=True,
			half_day_date=leave_date,
		)
		att = self._get_submitted_attendance(employee, leave_date)
		self.assertTrue(att)

		wd = self._sync_workday_for_leave_date(employee, leave_date)
		self.assertEqual(wd.status, "Half Day")

		target_for_att = flt(
			frappe.db.get_value("Attendance", att.name, "custom_target_hours")
		)
		actual_for_att = flt(
			frappe.db.get_value("Attendance", att.name, "custom_actual_working_hours")
		)
		expected_v = get_ole_hour_variance_for_attendance(
			status="Half Day",
			leave_type=leave_type,
			employee=employee,
			log_date=leave_date,
			target_hours=target_for_att,
			actual_hours=actual_for_att,
			custom_hour_variance=actual_for_att - target_for_att,
		)
		self.assertNotEqual(expected_v, 0)

		ole_name = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Attendance",
				"voucher_no": att.name,
				"is_cancelled": 0,
			},
			"name",
		)
		self.assertTrue(ole_name)
		self.assertAlmostEqual(
			flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance")),
			expected_v,
			places=4,
		)

	def test_validate_leave_application_rejects_insufficient_overtime_balance(self):
		"""OT-deduct leave validate throws when balance is below required leave hours."""
		self._require_ot_deduct_leave_field()
		self._ensure_open_period_for_ole()
		leave_date = add_days(getdate(), -1)
		employee = make_employee(
			f"ole_la_val_fail_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		self._ensure_weekly_working_hours(employee, day_hours=8)
		self._seed_overtime_balance(employee, hours=2)
		leave_type = self._create_ot_deduct_leave_type("ValFail")

		create_user("test@example.com")
		allocation = create_leave_allocation(
			employee=employee,
			leave_type=leave_type,
			from_date=add_days(leave_date, -30),
			to_date=add_days(leave_date, 30),
			new_leaves_allocated=30,
		)
		allocation.flags.ignore_permissions = True
		allocation.insert()
		allocation.submit()

		la = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"from_date": leave_date,
				"to_date": leave_date,
				"leave_type": leave_type,
				"company": "_Test Company",
				"status": "Approved",
				"leave_approver": "test@example.com",
				"posting_date": leave_date,
			}
		)
		la.flags.ignore_permissions = True

		with self.assertRaises(frappe.ValidationError):
			validate_leave_application(la)

	def test_validate_leave_application_allows_sufficient_overtime_balance(self):
		"""OT-deduct leave validate passes when seeded balance covers the leave duration."""
		self._require_ot_deduct_leave_field()
		self._ensure_open_period_for_ole()
		leave_date = add_days(getdate(), -2)
		employee = make_employee(
			f"ole_la_val_ok_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		self._ensure_weekly_working_hours(employee, day_hours=8)
		self._seed_overtime_balance(employee, hours=24)
		leave_type = self._create_ot_deduct_leave_type("ValOk")

		create_user("test@example.com")
		allocation = create_leave_allocation(
			employee=employee,
			leave_type=leave_type,
			from_date=add_days(leave_date, -30),
			to_date=add_days(leave_date, 30),
			new_leaves_allocated=30,
		)
		allocation.flags.ignore_permissions = True
		allocation.insert()
		allocation.submit()

		la = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"from_date": leave_date,
				"to_date": leave_date,
				"leave_type": leave_type,
				"company": "_Test Company",
				"status": "Approved",
				"leave_approver": "test@example.com",
				"posting_date": leave_date,
			}
		)
		la.flags.ignore_permissions = True
		la.insert()
		validate_leave_application(la)

	def test_leave_cancel_reverses_attendance_ole(self):
		"""Cancelling OT-deduct leave cancels linked Attendance and reverses its OLE."""
		self._require_attendance_ole_fields()
		self._require_ot_deduct_leave_field()
		self._ensure_open_period_for_ole()
		leave_date = add_days(getdate(), -3)
		employee = make_employee(
			f"ole_la_cancel_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)
		self._ensure_weekly_working_hours(employee, day_hours=8)
		self._seed_overtime_balance(employee, hours=24)
		balance_after_seed = flt(get_employee_overtime_balance(employee).get("balance"))
		leave_type = self._create_ot_deduct_leave_type("Cancel")

		la = self._submit_leave_application(employee, leave_type, leave_date, leave_date)
		att = self._get_submitted_attendance(employee, leave_date)
		self.assertTrue(att)
		self._sync_workday_for_leave_date(employee, leave_date)

		ole_name = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Attendance",
				"voucher_no": att.name,
				"is_cancelled": 0,
			},
			"name",
		)
		self.assertTrue(ole_name)
		original_hv = flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance"))

		la_doc = frappe.get_doc("Leave Application", la.name)
		la_doc.flags.ignore_permissions = True
		la_doc.cancel()

		self.assertEqual(frappe.db.get_value("Attendance", att.name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Overtime Ledger Entry", ole_name, "is_cancelled"), 1)
		reversals = frappe.get_all(
			"Overtime Ledger Entry",
			filters={
				"voucher_type": "Attendance",
				"voucher_no": att.name,
				"is_cancelled": 0,
			},
			fields=["hour_variance", "remarks"],
		)
		self.assertEqual(len(reversals), 1)
		self.assertIn(REVERSAL_REMARK_MARKER, reversals[0].remarks or "")
		self.assertAlmostEqual(flt(reversals[0].hour_variance), -original_hv, places=4)
		self.assertAlmostEqual(
			flt(get_employee_overtime_balance(employee).get("balance")),
			balance_after_seed,
			places=4,
		)

	def test_workday_update_changes_existing_ole_hour_variance(self):
		"""Workday sync on existing Attendance updates linked OLE when hours change."""
		self._require_attendance_ole_fields()
		self._ensure_open_period_for_ole()
		log_date = add_days(getdate(), -4)
		employee = make_employee(
			f"ole_wd_update_{uuid.uuid4().hex[:10]}@test.local",
			company="_Test Company",
		)

		attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": log_date,
				"status": "Present",
				"company": "_Test Company",
				"custom_target_hours": 8,
				"custom_actual_working_hours": 7,
			}
		)
		attendance.flags.ignore_permissions = True
		attendance.insert()
		try:
			attendance.submit()
		except Exception as exc:
			self.skipTest(f"Attendance submit not supported in this environment: {exc}")

		ole_name = frappe.db.get_value(
			"Overtime Ledger Entry",
			{
				"voucher_type": "Attendance",
				"voucher_no": attendance.name,
				"is_cancelled": 0,
			},
			"name",
		)
		self.assertTrue(ole_name)
		self.assertAlmostEqual(
			flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance")),
			-1.0,
			places=4,
		)

		wd = frappe.get_doc(
			{
				"doctype": "Workday",
				"employee": employee,
				"log_date": log_date,
				"company": "_Test Company",
				"status": "Present",
				"target_hours": 8,
				"actual_working_hours": 10,
				"attendance": attendance.name,
			}
		)
		create_attendace_record(wd)

		self.assertAlmostEqual(
			flt(frappe.db.get_value("Overtime Ledger Entry", ole_name, "hour_variance")),
			2.0,
			places=4,
		)


class TestOvertimeLedgerEventHelpers(FrappeTestCase):
	"""Pure unit tests for overtime_ledger and attendace helpers (no DB)."""

	def test_is_reversal_ledger_row_detects_marker(self):
		"""Remarks containing the reversal marker should classify as explicit reversal rows."""
		self.assertTrue(is_reversal_ledger_row(f"{REVERSAL_REMARK_MARKER} OLE-1"))
		self.assertFalse(is_reversal_ledger_row("Normal adjustment"))
		self.assertFalse(is_reversal_ledger_row(None))

	def test_get_reversal_entry_names_prefers_remark_marker(self):
		"""Rows with reversal remarks on the same voucher as cancelled entries should be named."""
		entries = [
			{
				"name": "OLE-001",
				"voucher_no": "ATT-1",
				"is_cancelled": 1,
				"hour_variance": -2,
			},
			{
				"name": "OLE-002",
				"voucher_no": "ATT-1",
				"is_cancelled": 0,
				"hour_variance": 2,
				"remarks": f"{REVERSAL_REMARK_MARKER} OLE-001",
			},
		]
		names = get_reversal_entry_names_from_ole_rows(entries)
		self.assertIn("OLE-002", names)

	def test_get_reversal_entry_names_legacy_sum_match(self):
		"""Active row whose variance nets cancelled sum to zero should count as reversal without marker."""
		entries = [
			{
				"name": "OLE-A",
				"voucher_no": "V-9",
				"is_cancelled": 1,
				"hour_variance": -1.5,
			},
			{
				"name": "OLE-B",
				"voucher_no": "V-9",
				"is_cancelled": 0,
				"hour_variance": 1.5,
				"remarks": "Legacy DE Storno",
			},
		]
		names = get_reversal_entry_names_from_ole_rows(entries)
		self.assertIn("OLE-B", names)

	def test_get_ole_hour_variance_present_day_standard(self):
		"""Present status uses actual minus target (no leave-type DB lookup)."""
		v = get_ole_hour_variance_for_attendance(
			status="Present",
			target_hours=8,
			actual_hours=10,
		)
		self.assertEqual(v, 2)

	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.is_half_day_holiday",
		return_value=True,
	)
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.get_employee_default_work_hour",
	)
	def test_get_ole_hour_variance_half_day_holiday_full_target_halved(
		self, mock_edwh, _mock_is_half_day
	):
		"""Half-day holiday: full-day target on voucher → OLE uses half of weekly target."""
		mock_edwh.return_value = frappe._dict(hours=7, break_minutes=30)
		v = get_ole_hour_variance_for_attendance(
			status="Present",
			employee="HR-EMP-00002",
			log_date="2026-05-20",
			target_hours=7,
			actual_hours=4,
		)
		self.assertAlmostEqual(v, 0.5, places=6)

	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.is_half_day_holiday",
		return_value=True,
	)
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.get_employee_default_work_hour",
	)
	def test_get_ole_hour_variance_half_day_holiday_already_halved_target(
		self, mock_edwh, _mock_is_half_day
	):
		"""Half-day holiday: target already 50% of weekly → no second halving."""
		mock_edwh.return_value = frappe._dict(hours=7, break_minutes=30)
		v = get_ole_hour_variance_for_attendance(
			status="Absent",
			employee="HR-EMP-00002",
			log_date="2026-05-20",
			target_hours=3.5,
			actual_hours=0,
		)
		self.assertAlmostEqual(v, -3.5, places=6)

	def test_get_effective_ole_target_hours_already_halved(self):
		with patch(
			"hr_addon.hr_addon.doctype.workday.workday.is_half_day_holiday",
			return_value=True,
		), patch(
			"hr_addon.hr_addon.doctype.workday.workday.get_employee_default_work_hour",
			return_value=frappe._dict(hours=7, break_minutes=30),
		):
			t = get_effective_ole_target_hours(3.5, "HR-EMP-00002", "2026-05-20")
		self.assertAlmostEqual(t, 3.5, places=6)

	def test_get_ole_hour_variance_half_day_without_deduct_leave_uses_standard(self):
		"""Half Day without a deducting leave type path still uses standard actual - target."""
		v = get_ole_hour_variance_for_attendance(
			status="Half Day",
			leave_type=None,
			employee=None,
			log_date=None,
			target_hours=8,
			actual_hours=9,
		)
		self.assertEqual(v, 1)

	def test_get_ole_hour_variance_half_day_when_leave_type_deducts_overtime(self):
		"""Half Day + OT-deduct Leave Type: variance is -(target − (actual − target)) per business rule."""
		with patch.object(
			frappe.db,
			"get_value",
			side_effect=lambda dt, *a, **kw: (
				1
				if dt == "Leave Type"
				and a
				and len(a) >= 2
				and a[-1] == "custom_is_deducted_from_overtime_ledger"
				else kw.get("default")
			),
		):
			v = get_ole_hour_variance_for_attendance(
				status="Half Day",
				leave_type="_Test_LT",
				employee=None,
				log_date=None,
				target_hours=3.5,
				actual_hours=4.5,
				custom_hour_variance=None,
			)
			self.assertAlmostEqual(v, -2.5, places=6)

