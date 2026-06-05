# Copyright (c) 2022, phamos.eu and Contributors
# See license.txt

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime, getdate

from hr_addon.hr_addon.doctype.workday.workday import (
	MECHANISM_MINIMUM_BREAK_RULE,
	MECHANISMS_ACTUAL_WORKING_HOURS_FROM_ON_SITE,
	_cap_date_range_by_employee_dates,
	_create_new_attendance,
	_create_overtime_ledger_entry,
	_get_submitted_attendance_for_workday,
	_handle_overtime_ledger,
	_resolve_attendance_for_workday_trash,
	_update_existing_attendance,
	apply_half_day_holiday_targets,
	bulk_process_workdays,
	bulk_process_workdays_background,
	calculate_actual_working_hours,
	cancel_attendance,
	create_attendace_record,
	create_background_job_for_workday_generation,
	create_background_job_for_workday_generation_after_install,
	date_is_in_holiday_list,
	generate_workdays_for_past_7_days_now,
	generate_workdays_scheduled_job,
	get_actual_employee_log,
	get_created_workdays,
	get_employee_attendance,
	get_employee_checkin,
	get_employee_default_work_hour,
	get_holiday_not_workday_log,
	get_mandatory_break_hours_from_settings,
	get_month_map,
	get_submitted_leave_application,
	get_unmarked_days,
	get_unmarked_range,
	get_workday,
	has_valid_weekly_working_hours,
	is_half_day_holiday,
	is_leave_type_ot_deduct,
	set_attendance_in_employee_checkins,
)


def _default_minimum_break_rules():
	return [
		SimpleNamespace(from_hours=0, to_hours=6, minimum_break_minutes=0),
		SimpleNamespace(from_hours=6, to_hours=9, minimum_break_minutes=30),
		SimpleNamespace(from_hours=9, to_hours=100, minimum_break_minutes=45),
	]


def _make_settings(
	mechanism="Break Hours from Weekly Working Hours if Shorter breaks",
	swap_hours_worked_and_actual_working_hours=0,
	minimum_break_rule=None,
):
	return SimpleNamespace(
		workday_break_calculation_mechanism=mechanism,
		swap_hours_worked_and_actual_working_hours=swap_hours_worked_and_actual_working_hours,
		minimum_break_rule=(
			_default_minimum_break_rules()
			if minimum_break_rule is None
			else minimum_break_rule
		),
	)


def _make_default_work_hour(hours=8, break_minutes=30, **kwargs):
	return frappe._dict(
		hours=hours,
		break_minutes=break_minutes,
		no_break_hours=kwargs.get("no_break_hours", 0),
		set_target_hours_to_zero_when_date_is_holiday=kwargs.get(
			"set_target_hours_to_zero_when_date_is_holiday", 0
		),
	)


def _make_checkins(time_strings):
	"""Build alternating IN/OUT checkins from 'HH:MM:SS' strings."""
	checkins = []
	for idx, time_str in enumerate(time_strings):
		checkins.append(
			frappe._dict(
				name=f"EMP-CKIN-{idx:04d}",
				time=get_datetime(f"2026-06-02 {time_str}"),
				attendance=None,
				log_type="IN" if idx % 2 == 0 else "OUT",
			)
		)
	return checkins


@contextmanager
def patch_hr_addon_settings(settings):
	with patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_doc",
		return_value=settings,
	):
		yield


class TestGetMonthMap(FrappeTestCase):
	# get_month_map: returns month name to number mapping for all twelve months.
	def test_get_month_map_returns_twelve_months(self):
		month_map = get_month_map()
		self.assertEqual(month_map["January"], 1)
		self.assertEqual(month_map["June"], 6)
		self.assertEqual(month_map["December"], 12)
		self.assertEqual(len(month_map), 12)


class TestCapDateRangeByEmployeeDates(FrappeTestCase):
	# _cap_date_range_by_employee_dates: keeps range when no joining or relieving date.
	def test_cap_date_range_without_employee_dates(self):
		start, end = _cap_date_range_by_employee_dates(
			None, None, "2026-01-01", "2026-01-31"
		)
		self.assertEqual(getdate(start), getdate("2026-01-01"))
		self.assertEqual(getdate(end), getdate("2026-01-31"))

	# _cap_date_range_by_employee_dates: caps start at joining date when later than from_day.
	def test_cap_date_range_with_joining_date(self):
		start, end = _cap_date_range_by_employee_dates(
			getdate("2026-01-15"), None, "2026-01-01", "2026-01-31"
		)
		self.assertEqual(getdate(start), getdate("2026-01-15"))
		self.assertEqual(getdate(end), getdate("2026-01-31"))

	# _cap_date_range_by_employee_dates: caps end at relieving date when earlier than to_day.
	def test_cap_date_range_with_relieving_date(self):
		start, end = _cap_date_range_by_employee_dates(
			None, getdate("2026-01-20"), "2026-01-01", "2026-01-31"
		)
		self.assertEqual(getdate(start), getdate("2026-01-01"))
		self.assertEqual(getdate(end), getdate("2026-01-20"))


class TestGetUnmarkedDays(FrappeTestCase):
	# get_unmarked_days: returns past dates in month not yet marked as workdays.
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_datetime")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_value")
	def test_get_unmarked_days_returns_past_dates(self, mock_cached_value, mock_get_datetime):
		def _get_datetime_side_effect(value=None):
			if value is None:
				return get_datetime("2026-06-15 10:00:00")
			return get_datetime(value)

		mock_get_datetime.side_effect = _get_datetime_side_effect
		mock_cached_value.return_value = (None, None)
		unmarked = get_unmarked_days("HR-EMP-00001", "June")
		self.assertIn("2026-6-1", unmarked)
		self.assertIn("2026-6-14", unmarked)
		self.assertNotIn("2026-6-15", unmarked)


class TestGetUnmarkedRange(FrappeTestCase):
	# get_unmarked_range: returns empty list when employee has no weekly working hours.
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_default_work_hour")
	def test_get_unmarked_range_returns_empty_without_weekly_hours(self, mock_edwh):
		mock_edwh.return_value = None
		result = get_unmarked_range("HR-EMP-00001", "2026-06-01", "2026-06-07")
		self.assertEqual(result, [])

	# get_unmarked_range: returns dates in range without existing workdays.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_list")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_value")
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_default_work_hour")
	def test_get_unmarked_range_returns_unmarked_dates(
		self, mock_edwh, mock_cached_value, mock_get_list
	):
		mock_edwh.return_value = _make_default_work_hour()
		mock_cached_value.return_value = (None, None)
		mock_get_list.return_value = [frappe._dict(log_date="2026-06-01")]
		result = get_unmarked_range("HR-EMP-00001", "2026-06-01", "2026-06-03")
		self.assertEqual(result, ["2026-06-02", "2026-06-03"])


class TestGetCreatedWorkdays(FrappeTestCase):
	# get_created_workdays: formats workday list for calendar display.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_list")
	def test_get_created_workdays_formats_dates(self, mock_get_list):
		mock_get_list.return_value = [
			{"log_date": "2026-06-02", "name": "WD-00001", "employee": "HR-EMP-00001"}
		]
		result = get_created_workdays("HR-EMP-00001", "2026-06-01", "2026-06-30")
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["name"], "WD-00001")
		self.assertEqual(result[0]["log_date"], "02.06.2026")


def _mock_qb_query_chain(rows):
	mock_query = MagicMock()
	mock_query.select.return_value = mock_query
	mock_query.where.return_value = mock_query
	mock_query.left_join.return_value = mock_query
	mock_query.on.return_value = mock_query
	mock_query.orderby.return_value = mock_query
	mock_query.run.return_value = rows
	return mock_query


class TestGetEmployeeCheckin(FrappeTestCase):
	# get_employee_checkin: returns checkins for employee on given date.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.qb.from_")
	def test_get_employee_checkin_returns_checkin_rows(self, mock_from):
		mock_from.return_value = _mock_qb_query_chain(
			[{"name": "CI-1", "log_type": "IN", "time": get_datetime("2026-06-02 08:00:00")}]
		)
		result = get_employee_checkin("HR-EMP-00001", "2026-06-02")
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["name"], "CI-1")


class TestGetEmployeeDefaultWorkHour(FrappeTestCase):
	# get_employee_default_work_hour: returns None when skip enabled and no weekly hours.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.qb.from_")
	def test_get_employee_default_work_hour_returns_none_when_skipping(self, mock_from):
		mock_from.return_value = _mock_qb_query_chain([])
		result = get_employee_default_work_hour(
			"HR-EMP-00001", "2026-06-02", skip_workday_if_no_weekly_hours=1
		)
		self.assertIsNone(result)

	# get_employee_default_work_hour: returns weekly row when configured for weekday.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.qb.from_")
	def test_get_employee_default_work_hour_returns_weekly_row(self, mock_from):
		weekly_row = frappe._dict(hours=8, break_minutes=30, day="Monday")
		mock_from.return_value = _mock_qb_query_chain([weekly_row])
		result = get_employee_default_work_hour(
			"HR-EMP-00001", "2026-06-01", skip_workday_if_no_weekly_hours=1
		)
		self.assertEqual(result.hours, 8)
		self.assertEqual(result.break_minutes, 30)


class TestGetHolidayNotWorkdayLog(FrappeTestCase):
	# get_holiday_not_workday_log: zero target on holiday when configured.
	@patch("hr_addon.hr_addon.doctype.workday.workday.date_is_in_holiday_list", return_value=True)
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_attendance", return_value=[])
	def test_get_holiday_not_workday_log_zero_target_on_holiday(
		self, _mock_attendance, _mock_holiday
	):
		work_hour = _make_default_work_hour(
			set_target_hours_to_zero_when_date_is_holiday=1
		)
		result = get_holiday_not_workday_log("HR-EMP-00001", "2026-06-02", work_hour)
		self.assertEqual(result["status"], "Not Workday")
		self.assertEqual(result["target_hours"], 0)
		self.assertEqual(result["expected_break_hours"], 0)

	# get_holiday_not_workday_log: keeps weekly target when holiday zero-target is off.
	@patch("hr_addon.hr_addon.doctype.workday.workday.date_is_in_holiday_list", return_value=False)
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_attendance", return_value=[])
	def test_get_holiday_not_workday_log_keeps_weekly_target(
		self, _mock_attendance, _mock_holiday
	):
		work_hour = _make_default_work_hour(hours=8, break_minutes=30)
		result = get_holiday_not_workday_log("HR-EMP-00001", "2026-06-02", work_hour)
		self.assertEqual(result["target_hours"], 8)
		self.assertAlmostEqual(result["expected_break_hours"], 0.5)


class TestGetActualEmployeeLog(FrappeTestCase):
	# get_actual_employee_log: returns None when weekly hours missing and skip enabled.
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_default_work_hour")
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_checkin")
	def test_get_actual_employee_log_returns_none_without_weekly_hours(
		self, mock_checkin, mock_edwh
	):
		mock_checkin.return_value = []
		mock_edwh.return_value = None
		result = get_actual_employee_log("HR-EMP-00001", "2026-06-02")
		self.assertIsNone(result)

	# get_actual_employee_log: uses get_workday when checkins exist on normal day.
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_workday")
	@patch("hr_addon.hr_addon.doctype.workday.workday.date_is_in_holiday_list", return_value=False)
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_default_work_hour")
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_checkin")
	def test_get_actual_employee_log_delegates_to_get_workday(
		self, mock_checkin, mock_edwh, _mock_holiday, mock_get_workday
	):
		checkins = _make_checkins(["08:00:00", "17:00:00"])
		work_hour = _make_default_work_hour()
		mock_checkin.return_value = checkins
		mock_edwh.return_value = work_hour
		mock_get_workday.return_value = {"hours_worked": 8, "break_hours": 0.5}
		result = get_actual_employee_log("HR-EMP-00001", "2026-06-02")
		mock_get_workday.assert_called_once_with(checkins, work_hour, work_hour.no_break_hours)
		self.assertEqual(result["hours_worked"], 8)

	# get_actual_employee_log: returns holiday log on holiday without allow_workdays_on_holidays.
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_holiday_not_workday_log")
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_single_value",
		return_value=0,
	)
	@patch("hr_addon.hr_addon.doctype.workday.workday.date_is_in_holiday_list", return_value=True)
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_default_work_hour")
	@patch("hr_addon.hr_addon.doctype.workday.workday.get_employee_checkin")
	def test_get_actual_employee_log_uses_holiday_log_on_holiday(
		self, mock_checkin, mock_edwh, _mock_holiday, _mock_setting, mock_holiday_log
	):
		mock_checkin.return_value = _make_checkins(["08:00:00", "17:00:00"])
		mock_edwh.return_value = _make_default_work_hour()
		mock_holiday_log.return_value = {"status": "Not Workday"}
		result = get_actual_employee_log("HR-EMP-00001", "2026-06-02")
		mock_holiday_log.assert_called_once()
		self.assertEqual(result["status"], "Not Workday")


class TestSetAttendanceInEmployeeCheckins(FrappeTestCase):
	# set_attendance_in_employee_checkins: returns None when checkin list is empty.
	def test_set_attendance_in_employee_checkins_empty_list(self):
		self.assertIsNone(set_attendance_in_employee_checkins([], "ATT-00001"))

	# set_attendance_in_employee_checkins: updates checkin attendance when changed.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_doc")
	def test_set_attendance_in_employee_checkins_updates_checkin(self, mock_get_doc):
		checkin_doc = MagicMock(attendance=None)
		mock_get_doc.return_value = checkin_doc
		checkins = [{"employee_checkin": "CI-00001"}]
		updated = set_attendance_in_employee_checkins(checkins, "ATT-00001")
		self.assertTrue(updated)
		self.assertEqual(checkin_doc.attendance, "ATT-00001")
		checkin_doc.save.assert_called_once()


class TestGetMandatoryBreakHoursFromSettings(FrappeTestCase):
	"""Unit tests for Minimum Break Rule resolution by on-site duration."""

	def setUp(self):
		self.settings = _make_settings(minimum_break_rule=_default_minimum_break_rules())

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_doc")
	# get_mandatory_break_hours_from_settings: zero or negative on-site returns 0.
	def test_zero_or_negative_on_site_returns_zero(self, mock_get_cached_doc):
		mock_get_cached_doc.return_value = self.settings
		self.assertEqual(get_mandatory_break_hours_from_settings(0), 0)
		self.assertEqual(get_mandatory_break_hours_from_settings(-1), 0)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_doc")
	# get_mandatory_break_hours_from_settings: first band (0-6h) inclusive boundaries.
	def test_first_band_inclusive_boundaries(self, mock_get_cached_doc):
		mock_get_cached_doc.return_value = self.settings
		self.assertEqual(get_mandatory_break_hours_from_settings(4), 0)
		self.assertEqual(get_mandatory_break_hours_from_settings(6), 0)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_doc")
	# get_mandatory_break_hours_from_settings: middle band (6-9h) returns 30 minutes.
	def test_middle_band_strict_lower_and_inclusive_upper(self, mock_get_cached_doc):
		mock_get_cached_doc.return_value = self.settings
		self.assertAlmostEqual(get_mandatory_break_hours_from_settings(6.01), 0.5)
		self.assertAlmostEqual(get_mandatory_break_hours_from_settings(8.5), 0.5)
		self.assertAlmostEqual(get_mandatory_break_hours_from_settings(9), 0.5)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_doc")
	# get_mandatory_break_hours_from_settings: top band (9h+) returns 45 minutes.
	def test_top_band_and_open_ended_row(self, mock_get_cached_doc):
		mock_get_cached_doc.return_value = self.settings
		self.assertAlmostEqual(get_mandatory_break_hours_from_settings(9.01), 0.75)
		self.assertAlmostEqual(get_mandatory_break_hours_from_settings(10), 0.75)
		self.assertAlmostEqual(get_mandatory_break_hours_from_settings(12), 0.75)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_doc")
	# get_mandatory_break_hours_from_settings: no rules configured returns 0.
	def test_no_rules_configured_returns_zero(self, mock_get_cached_doc):
		mock_get_cached_doc.return_value = _make_settings(minimum_break_rule=[])
		self.assertEqual(get_mandatory_break_hours_from_settings(8), 0)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_doc")
	# get_mandatory_break_hours_from_settings: duration outside all bands returns 0.
	def test_unmatched_duration_returns_zero(self, mock_get_cached_doc):
		mock_get_cached_doc.return_value = _make_settings(
			minimum_break_rule=[
				SimpleNamespace(from_hours=10, to_hours=11, minimum_break_minutes=60),
			]
		)
		self.assertEqual(get_mandatory_break_hours_from_settings(8), 0)


class TestCalculateActualWorkingHours(FrappeTestCase):
	"""Unit tests for actual_working_hours across mechanisms and edge cases."""

	# calculate_actual_working_hours: If Shorter breaks uses on-site minus break.
	def test_if_shorter_breaks_uses_on_site_minus_break(self):
		actual = calculate_actual_working_hours(
			hours_worked=9,
			break_hours=0.75,
			default_break_hours=0.5,
			mechanism="Break Hours from Weekly Working Hours if Shorter breaks",
			total_duration=9.5,
			is_swapped=False,
		)
		self.assertAlmostEqual(actual, 8.75)

	# calculate_actual_working_hours: Minimum Break Rule uses on-site minus break.
	def test_minimum_break_rule_uses_on_site_minus_break(self):
		actual = calculate_actual_working_hours(
			hours_worked=9,
			break_hours=1,
			default_break_hours=0.5,
			mechanism=MECHANISM_MINIMUM_BREAK_RULE,
			total_duration=9.5,
			is_swapped=False,
		)
		self.assertAlmostEqual(actual, 8.5)

	# calculate_actual_working_hours: Employee Checkins uses hours worked minus break.
	def test_employee_checkins_uses_hours_worked_minus_break(self):
		actual = calculate_actual_working_hours(
			hours_worked=8,
			break_hours=0.5,
			default_break_hours=0.5,
			mechanism="Break Hours from Employee Checkins",
			total_duration=8.5,
			is_swapped=False,
		)
		self.assertAlmostEqual(actual, 7.5)

	# calculate_actual_working_hours: Weekly Working Hours uses hours worked minus weekly break.
	def test_weekly_working_hours_uses_hours_worked_minus_break(self):
		actual = calculate_actual_working_hours(
			hours_worked=8,
			break_hours=0.5,
			default_break_hours=0.5,
			mechanism="Break Hours from Weekly Working Hours",
			total_duration=8.5,
			is_swapped=False,
		)
		self.assertAlmostEqual(actual, 7.5)

	# calculate_actual_working_hours: no_break_hours skips deduction below threshold.
	def test_no_break_hours_below_threshold_returns_hours_worked(self):
		actual = calculate_actual_working_hours(
			hours_worked=5,
			break_hours=0.5,
			default_break_hours=0.5,
			mechanism="Break Hours from Weekly Working Hours",
			total_duration=5.5,
			is_swapped=False,
			no_break_hours=True,
			hours_worked_threshold=6,
		)
		self.assertAlmostEqual(actual, 5)

	# calculate_actual_working_hours: no_break_hours ignored when hours are swapped.
	def test_no_break_hours_not_applied_when_swapped(self):
		actual = calculate_actual_working_hours(
			hours_worked=5,
			break_hours=0.5,
			default_break_hours=0.5,
			mechanism="Break Hours from Employee Checkins",
			total_duration=5.5,
			is_swapped=True,
			no_break_hours=True,
			hours_worked_threshold=6,
		)
		self.assertAlmostEqual(actual, 5)

	# calculate_actual_working_hours: swapped mechanism uses total duration minus break.
	def test_swapped_mechanism_uses_total_duration_minus_break(self):
		actual = calculate_actual_working_hours(
			hours_worked=8.5,
			break_hours=0.5,
			default_break_hours=0.5,
			mechanism="Break Hours from Employee Checkins",
			total_duration=8,
			is_swapped=True,
		)
		self.assertAlmostEqual(actual, 7.5)

	# calculate_actual_working_hours: on-site mechanisms fall back without total duration.
	def test_on_site_mechanisms_fallback_without_total_duration(self):
		for mechanism in MECHANISMS_ACTUAL_WORKING_HOURS_FROM_ON_SITE:
			actual = calculate_actual_working_hours(
				hours_worked=8,
				break_hours=0.5,
				default_break_hours=0.5,
				mechanism=mechanism,
				total_duration=None,
				is_swapped=False,
			)
			self.assertAlmostEqual(actual, 7.5, msg=mechanism)

	# calculate_actual_working_hours: weekly mechanism uses default break without on-site time.
	def test_legacy_mechanism_without_total_duration_uses_default_break(self):
		actual = calculate_actual_working_hours(
			hours_worked=8,
			break_hours=0.5,
			default_break_hours=0.5,
			mechanism="Break Hours from Weekly Working Hours",
			total_duration=None,
			is_swapped=False,
		)
		self.assertAlmostEqual(actual, 7.5)


class TestGetWorkdayBreakMechanisms(FrappeTestCase):
	"""Integration-style tests for get_workday() break fields per mechanism."""

	def setUp(self):
		self.default_work_hour = _make_default_work_hour(hours=8, break_minutes=30)
		self.checkins_9_5h_with_half_hour_break = _make_checkins(
			["08:00:00", "12:30:00", "13:00:00", "17:30:00"]
		)
		self.checkins_9_5h_with_one_hour_break = _make_checkins(
			["08:00:00", "12:30:00", "13:30:00", "17:30:00"]
		)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: Employee Checkins uses real check-in gap as break hours.
	def test_employee_checkins_mechanism(self, _mock_get_value):
		settings = _make_settings(mechanism="Break Hours from Employee Checkins")
		with patch_hr_addon_settings(settings):
			result = get_workday(
				self.checkins_9_5h_with_half_hour_break,
				self.default_work_hour,
				no_break_hours=False,
			)
		self.assertAlmostEqual(result["hours_worked"], 9)
		self.assertAlmostEqual(result["expected_break_hours"], 0.5)
		self.assertAlmostEqual(result["break_hours"], 0.5)
		self.assertAlmostEqual(result["actual_working_hours"], 8.5)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: Weekly Working Hours always applies weekly break_minutes.
	def test_weekly_working_hours_mechanism(self, _mock_get_value):
		settings = _make_settings(mechanism="Break Hours from Weekly Working Hours")
		with patch_hr_addon_settings(settings):
			result = get_workday(
				self.checkins_9_5h_with_one_hour_break,
				self.default_work_hour,
				no_break_hours=False,
			)
		self.assertAlmostEqual(result["hours_worked"], 8.5)
		self.assertAlmostEqual(result["expected_break_hours"], 0.5)
		self.assertAlmostEqual(result["break_hours"], 0.5)
		self.assertAlmostEqual(result["actual_working_hours"], 8)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: If Shorter breaks applies weekly break when gap is shorter.
	def test_if_shorter_breaks_applies_weekly_when_gap_shorter(self, _mock_get_value):
		settings = _make_settings(
			mechanism="Break Hours from Weekly Working Hours if Shorter breaks"
		)
		with patch_hr_addon_settings(settings):
			result = get_workday(
				self.checkins_9_5h_with_half_hour_break,
				self.default_work_hour,
				no_break_hours=False,
			)
		self.assertAlmostEqual(result["expected_break_hours"], 0.5)
		self.assertAlmostEqual(result["break_hours"], 0.5)
		self.assertAlmostEqual(result["actual_working_hours"], 9)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: If Shorter breaks uses real gap when longer than weekly break.
	def test_if_shorter_breaks_uses_real_gap_when_longer(self, _mock_get_value):
		settings = _make_settings(
			mechanism="Break Hours from Weekly Working Hours if Shorter breaks"
		)
		with patch_hr_addon_settings(settings):
			result = get_workday(
				self.checkins_9_5h_with_one_hour_break,
				self.default_work_hour,
				no_break_hours=False,
			)
		self.assertAlmostEqual(result["expected_break_hours"], 0.5)
		self.assertAlmostEqual(result["break_hours"], 1)
		self.assertAlmostEqual(result["actual_working_hours"], 8.5)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: Minimum Break Rule applies mandatory break when gap is shorter.
	def test_minimum_break_rule_applies_mandatory_when_gap_shorter(self, _mock_get_value):
		settings = _make_settings(mechanism=MECHANISM_MINIMUM_BREAK_RULE)
		with patch_hr_addon_settings(settings):
			result = get_workday(
				self.checkins_9_5h_with_half_hour_break,
				self.default_work_hour,
				no_break_hours=False,
			)
		self.assertAlmostEqual(result["expected_break_hours"], 0.75)
		self.assertAlmostEqual(result["break_hours"], 0.75)
		self.assertAlmostEqual(result["actual_working_hours"], 8.75)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: Minimum Break Rule uses real gap when longer than mandatory.
	def test_minimum_break_rule_uses_real_gap_when_longer(self, _mock_get_value):
		settings = _make_settings(mechanism=MECHANISM_MINIMUM_BREAK_RULE)
		with patch_hr_addon_settings(settings):
			result = get_workday(
				self.checkins_9_5h_with_one_hour_break,
				self.default_work_hour,
				no_break_hours=False,
			)
		self.assertAlmostEqual(result["expected_break_hours"], 0.75)
		self.assertAlmostEqual(result["break_hours"], 1)
		self.assertAlmostEqual(result["actual_working_hours"], 8.5)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: no_break_hours skips break deduction when hours worked is below 6h.
	def test_no_break_hours_short_day_skips_break_deduction(self, _mock_get_value):
		checkins = _make_checkins(["08:00:00", "11:00:00", "11:30:00", "13:30:00"])
		settings = _make_settings(mechanism="Break Hours from Weekly Working Hours")
		work_hour = _make_default_work_hour(hours=6, break_minutes=30, no_break_hours=1)
		with patch_hr_addon_settings(settings):
			result = get_workday(checkins, work_hour, no_break_hours=True)
		self.assertAlmostEqual(result["hours_worked"], 5)
		self.assertAlmostEqual(result["break_hours"], 0.5)
		self.assertAlmostEqual(result["actual_working_hours"], 5)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: swapped hours exchanges on-site time and hours worked.
	def test_swapped_checkins_mechanism(self, _mock_get_value):
		settings = _make_settings(
			mechanism="Break Hours from Employee Checkins",
			swap_hours_worked_and_actual_working_hours=1,
		)
		with patch_hr_addon_settings(settings):
			result = get_workday(
				self.checkins_9_5h_with_half_hour_break,
				self.default_work_hour,
				no_break_hours=False,
			)
		self.assertAlmostEqual(result["hours_worked"], 9.5)
		self.assertAlmostEqual(result["break_hours"], 0.5)
		self.assertAlmostEqual(result["actual_working_hours"], 8.5)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: odd number of checkins returns Missing Checkin with zero hours.
	def test_odd_number_of_checkins_returns_missing_checkin(self, _mock_get_value):
		checkins = _make_checkins(["08:00:00", "12:00:00", "13:00:00"])
		settings = _make_settings(mechanism=MECHANISM_MINIMUM_BREAK_RULE)
		with patch_hr_addon_settings(settings):
			result = get_workday(checkins, self.default_work_hour, no_break_hours=False)
		self.assertEqual(result["status"], "Missing Checkin")
		self.assertEqual(result["hours_worked"], 0)
		self.assertEqual(result["break_hours"], 0)
		self.assertEqual(result["actual_working_hours"], 0)

	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=None)
	# get_workday: unknown break mechanism defaults break hours to zero.
	def test_unknown_mechanism_sets_zero_break_hours(self, _mock_get_value):
		settings = _make_settings(mechanism="Unknown Mechanism")
		with patch_hr_addon_settings(settings):
			result = get_workday(
				self.checkins_9_5h_with_half_hour_break,
				self.default_work_hour,
				no_break_hours=False,
			)
		self.assertEqual(result["break_hours"], 0)


class TestGetEmployeeAttendance(FrappeTestCase):
	# get_employee_attendance: returns attendance rows for employee on date.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.qb.from_")
	def test_get_employee_attendance_returns_rows(self, mock_from):
		mock_from.return_value = _mock_qb_query_chain(
			[{"name": "ATT-00001", "status": "Present"}]
		)
		result = get_employee_attendance("HR-EMP-00001", "2026-06-02")
		self.assertEqual(result[0]["name"], "ATT-00001")


class TestIsHalfDayHoliday(FrappeTestCase):
	# is_half_day_holiday: returns True when date exists in HR Addon half-day holidays.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.exists", return_value="HDH-00001")
	def test_is_half_day_holiday_returns_true(self, _mock_exists):
		self.assertTrue(is_half_day_holiday("2026-06-02"))

	# is_half_day_holiday: returns False when date is not configured.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.exists", return_value=None)
	def test_is_half_day_holiday_returns_false(self, _mock_exists):
		self.assertFalse(is_half_day_holiday("2026-06-02"))


class TestApplyHalfDayHolidayTargets(FrappeTestCase):
	# apply_half_day_holiday_targets: halves target and expected break on half-day holiday.
	@patch("hr_addon.hr_addon.doctype.workday.workday.is_half_day_holiday", return_value=True)
	def test_apply_half_day_holiday_targets_halves_existing_targets(self, _mock_half_day):
		doc = frappe._dict(
			log_date="2026-06-02",
			status="Present",
			target_hours=8,
			expected_break_hours=0.5,
		)
		apply_half_day_holiday_targets(doc)
		self.assertEqual(doc.target_hours, 4)
		self.assertEqual(doc.expected_break_hours, 0.25)

	# apply_half_day_holiday_targets: skips when status is already On Leave.
	@patch("hr_addon.hr_addon.doctype.workday.workday.is_half_day_holiday", return_value=True)
	def test_apply_half_day_holiday_targets_skips_on_leave(self, _mock_half_day):
		doc = frappe._dict(
			log_date="2026-06-02",
			status="On Leave",
			target_hours=8,
			expected_break_hours=0.5,
		)
		apply_half_day_holiday_targets(doc)
		self.assertEqual(doc.target_hours, 8)


class TestDateIsInHolidayList(FrappeTestCase):
	# date_is_in_holiday_list: returns False when employee has no holiday list.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.msgprint")
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_value",
		return_value=None,
	)
	def test_date_is_in_holiday_list_without_holiday_list(self, _mock_cached, _mock_msgprint):
		self.assertFalse(date_is_in_holiday_list("HR-EMP-00001", "2026-06-02"))

	# date_is_in_holiday_list: returns True when date exists in employee holiday list.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.qb.from_")
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.get_cached_value",
		return_value="Test Holidays",
	)
	def test_date_is_in_holiday_list_when_date_is_holiday(self, _mock_cached, mock_from):
		mock_from.return_value = _mock_qb_query_chain([{"holiday_date": "2026-06-02"}])
		self.assertTrue(date_is_in_holiday_list("HR-EMP-00001", "2026-06-02"))


class TestCreateBackgroundJobForWorkdayGeneration(FrappeTestCase):
	# create_background_job_for_workday_generation: skips when scheduler is disabled.
	@patch(
		"frappe.core.doctype.scheduled_job_type.scheduled_job_type.insert_single_event",
	)
	def test_create_background_job_skips_when_disabled(self, mock_insert):
		settings = SimpleNamespace(enabled=0, time=23, background_job_frequency="Daily", day="Friday")
		create_background_job_for_workday_generation(settings)
		mock_insert.assert_not_called()

	# create_background_job_for_workday_generation: registers daily cron when enabled.
	@patch(
		"frappe.core.doctype.scheduled_job_type.scheduled_job_type.insert_single_event",
	)
	def test_create_background_job_registers_daily_cron(self, mock_insert):
		settings = SimpleNamespace(enabled=1, time=23, background_job_frequency="Daily", day="Friday")
		create_background_job_for_workday_generation(settings)
		mock_insert.assert_called_once()
		self.assertEqual(mock_insert.call_args.kwargs["frequency"], "Cron")
		self.assertIn("23", mock_insert.call_args.kwargs["cron_format"])


class TestCreateBackgroundJobAfterInstall(FrappeTestCase):
	# create_background_job_for_workday_generation_after_install: loads settings and registers job.
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.create_background_job_for_workday_generation"
	)
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_doc")
	def test_create_background_job_after_install(self, mock_get_doc, mock_create_job):
		settings = SimpleNamespace(enabled=1)
		mock_get_doc.return_value = settings
		create_background_job_for_workday_generation_after_install()
		mock_get_doc.assert_called_once_with("HR Addon Settings")
		mock_create_job.assert_called_once_with(settings)


class TestGenerateWorkdaysScheduledJob(FrappeTestCase):
	# generate_workdays_scheduled_job: skips generation when scheduler is disabled.
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.generate_workdays_for_past_7_days_now"
	)
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_doc")
	def test_generate_workdays_scheduled_job_skips_when_disabled(
		self, mock_get_doc, mock_generate
	):
		mock_get_doc.return_value = SimpleNamespace(enabled=0)
		generate_workdays_scheduled_job()
		mock_generate.assert_not_called()

	# generate_workdays_scheduled_job: runs generation when scheduler is enabled.
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.generate_workdays_for_past_7_days_now"
	)
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_doc")
	def test_generate_workdays_scheduled_job_runs_when_enabled(
		self, mock_get_doc, mock_generate
	):
		mock_get_doc.return_value = SimpleNamespace(enabled=1)
		generate_workdays_scheduled_job()
		mock_generate.assert_called_once()


class TestGenerateWorkdaysForPast7DaysNow(FrappeTestCase):
	# generate_workdays_for_past_7_days_now: finishes log when no active employees are found.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.utils.now_datetime")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.commit")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_list", return_value=[])
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_doc")
	def test_generate_workdays_for_past_7_days_now_with_no_employees(
		self, mock_get_doc, _mock_get_list, _mock_commit, mock_now_datetime
	):
		mock_now_datetime.return_value = get_datetime("2026-06-15 10:00:00")
		log_doc = SimpleNamespace(
			name="LOG-00001",
			status="Running",
			total_employees=0,
			total_dates_processed=0,
			workdays_created=0,
			workdays_failed=0,
			duration=0,
			error_log=None,
			employee_logs=[],
			insert=lambda **kwargs: None,
			save=lambda **kwargs: None,
			append=lambda *args, **kwargs: None,
		)
		settings = SimpleNamespace(skip_workday_if_no_weekly_hours=0)

		def get_doc_side_effect(doctype_or_data, *args, **kwargs):
			if isinstance(doctype_or_data, dict):
				return log_doc
			if doctype_or_data == "HR Addon Settings":
				return settings
			return log_doc

		mock_get_doc.side_effect = get_doc_side_effect
		generate_workdays_for_past_7_days_now()
		self.assertEqual(log_doc.status, "Failed")
		self.assertEqual(log_doc.total_employees, 0)


class TestHasValidWeeklyWorkingHours(FrappeTestCase):
	# has_valid_weekly_working_hours: returns False when no submitted weekly hours exist.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_all", return_value=[])
	def test_has_valid_weekly_working_hours_false_without_weekly_hours(self, _mock_get_all):
		self.assertFalse(has_valid_weekly_working_hours("HR-EMP-00001", "2026-06-02"))

	# has_valid_weekly_working_hours: returns True when weekday row exists in weekly hours.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.exists", return_value="DHD-00001")
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_all",
		return_value=[frappe._dict(name="WWH-00001")],
	)
	def test_has_valid_weekly_working_hours_true_with_day_row(self, _mock_get_all, _mock_exists):
		self.assertTrue(has_valid_weekly_working_hours("HR-EMP-00001", "2026-06-02"))


class TestBulkProcessWorkdaysBackground(FrappeTestCase):
	# bulk_process_workdays_background: enqueues bulk_process_workdays on long queue.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.enqueue")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.msgprint")
	def test_bulk_process_workdays_background_enqueues_job(self, _mock_msgprint, mock_enqueue):
		data = {"employee": "HR-EMP-00001", "unmarked_days": ["2026-06-02"]}
		bulk_process_workdays_background(data, "Create workday")
		mock_enqueue.assert_called_once()
		self.assertEqual(
			mock_enqueue.call_args.kwargs["queue"],
			"long",
		)


class TestBulkProcessWorkdays(FrappeTestCase):
	# bulk_process_workdays: throws when employee is not active.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_value", return_value="Left")
	def test_bulk_process_workdays_throws_for_inactive_employee(self, _mock_get_value):
		data = {
			"employee": "HR-EMP-00001",
			"unmarked_days": ["2026-06-02"],
		}
		with self.assertRaises(frappe.ValidationError):
			bulk_process_workdays(data, "Create workday")


class TestIsLeaveTypeOtDeduct(FrappeTestCase):
	# is_leave_type_ot_deduct: returns False when leave type is empty.
	def test_is_leave_type_ot_deduct_false_without_leave_type(self):
		self.assertFalse(is_leave_type_ot_deduct(None))

	# is_leave_type_ot_deduct: returns field value when custom overtime field exists.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value", return_value=1)
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.get_meta",
	)
	def test_is_leave_type_ot_deduct_true_when_field_enabled(self, mock_get_meta, _mock_get_value):
		mock_get_meta.return_value = SimpleNamespace(
			has_field=lambda fieldname: fieldname == "custom_is_deducted_from_overtime_ledger"
		)
		self.assertTrue(is_leave_type_ot_deduct("Casual Leave"))


class TestGetSubmittedLeaveApplication(FrappeTestCase):
	# get_submitted_leave_application: returns None when no submitted leave exists.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.exists", return_value=None)
	def test_get_submitted_leave_application_none(self, _mock_exists):
		self.assertIsNone(get_submitted_leave_application("HR-EMP-00001", "2026-06-02"))

	# get_submitted_leave_application: returns approved leave application details.
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value",
		side_effect=["Approved", "Casual Leave"],
	)
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.exists", return_value="LA-00001")
	def test_get_submitted_leave_application_returns_approved_leave(
		self, _mock_exists, _mock_get_value
	):
		result = get_submitted_leave_application("HR-EMP-00001", "2026-06-02")
		self.assertEqual(result.name, "LA-00001")
		self.assertEqual(result.leave_type, "Casual Leave")


class TestGetSubmittedAttendanceForWorkday(FrappeTestCase):
	# _get_submitted_attendance_for_workday: returns linked attendance when submitted.
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value",
		return_value=1,
	)
	def test_get_submitted_attendance_for_workday_from_link(self, _mock_get_value):
		doc = frappe._dict(attendance="ATT-00001", employee="HR-EMP-00001", log_date="2026-06-02")
		self.assertEqual(_get_submitted_attendance_for_workday(doc), "ATT-00001")

	# _get_submitted_attendance_for_workday: falls back to employee/date lookup.
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.db.exists",
		return_value="ATT-00002",
	)
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value",
		return_value=0,
	)
	def test_get_submitted_attendance_for_workday_fallback_lookup(
		self, _mock_get_value, _mock_exists
	):
		doc = frappe._dict(attendance=None, employee="HR-EMP-00001", log_date="2026-06-02")
		self.assertEqual(_get_submitted_attendance_for_workday(doc), "ATT-00002")


class TestCreateAttendanceRecord(FrappeTestCase):
	# create_attendace_record: skips new attendance when overtime ledger is disabled.
	@patch(
		"hr_addon.events.overtime_ledger.is_overtime_ledger_enabled",
		return_value=False,
	)
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday._get_submitted_attendance_for_workday",
		return_value=None,
	)
	def test_create_attendace_record_skips_when_ole_disabled(
		self, _mock_existing, _mock_ole_enabled
	):
		doc = frappe._dict(
			name="WD-00001",
			employee="HR-EMP-00001",
			log_date="2026-06-02",
			status="Present",
			target_hours=8,
			actual_working_hours=8,
		)
		self.assertIsNone(create_attendace_record(doc))


class TestCreateNewAttendance(FrappeTestCase):
	# _create_new_attendance: inserts and submits attendance linked to workday.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.commit")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.set_value")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.msgprint")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_doc")
	def test_create_new_attendance_submits_attendance(
		self, mock_get_doc, _mock_msgprint, _mock_set_value, _mock_commit
	):
		attendance = MagicMock(name="ATT-NEW")
		mock_get_doc.return_value = attendance
		doc = frappe._dict(
			name="WD-00001",
			employee="HR-EMP-00001",
			log_date="2026-06-02",
			company="Test Company",
		)
		_create_new_attendance(doc, 0, "Present", 8, 8)
		attendance.insert.assert_called_once()
		attendance.submit.assert_called_once()


class TestUpdateExistingAttendance(FrappeTestCase):
	# _update_existing_attendance: updates attendance hours and triggers overtime ledger handler.
	@patch("hr_addon.hr_addon.doctype.workday.workday._handle_overtime_ledger")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.set_value")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.msgprint")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_doc")
	def test_update_existing_attendance_updates_fields(
		self, mock_get_doc, _mock_msgprint, mock_set_value, mock_handle_ole
	):
		attendance = MagicMock(name="ATT-00001", in_time=None, out_time=None)
		mock_get_doc.return_value = attendance
		doc = frappe._dict(name="WD-00001", employee="HR-EMP-00001", log_date="2026-06-02")
		_update_existing_attendance(doc, "ATT-00001", 1, "Present", 8, 9)
		mock_set_value.assert_called()
		mock_handle_ole.assert_called_once()


class TestHandleOvertimeLedger(FrappeTestCase):
	# _handle_overtime_ledger: skips when overtime ledger feature is disabled.
	@patch(
		"hr_addon.events.overtime_ledger.is_overtime_ledger_enabled",
		return_value=False,
	)
	def test_handle_overtime_ledger_skips_when_disabled(self, _mock_ole_enabled):
		doc = frappe._dict(status="Present", employee="HR-EMP-00001", log_date="2026-06-02")
		attendance = MagicMock(custom_overtime_ledger_entry=None)
		self.assertIsNone(_handle_overtime_ledger(doc, attendance, 1, 8, 9))


class TestCreateOvertimeLedgerEntry(FrappeTestCase):
	# _create_overtime_ledger_entry: creates OLE and links it to attendance.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.commit")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.set_value")
	@patch(
		"hr_addon.hr_addon.doctype.overtime_ledger_entry.overtime_ledger_entry.make_ole_entry"
	)
	def test_create_overtime_ledger_entry_links_ole_to_attendance(
		self, mock_make_ole, _mock_set_value, _mock_commit
	):
		mock_make_ole.return_value = SimpleNamespace(name="OLE-00001")
		doc = frappe._dict(
			employee="HR-EMP-00001",
			log_date="2026-06-02",
			last_checkout=None,
		)
		attendance = MagicMock(name="ATT-00001", out_time=None)
		_create_overtime_ledger_entry(doc, attendance, 1, 8, 9)
		mock_make_ole.assert_called_once()


class TestResolveAttendanceForWorkdayTrash(FrappeTestCase):
	# _resolve_attendance_for_workday_trash: returns doc.attendance when already set.
	def test_resolve_attendance_for_workday_trash_from_doc(self):
		doc = frappe._dict(attendance="ATT-00001", employee="HR-EMP-00001", log_date="2026-06-02")
		self.assertEqual(_resolve_attendance_for_workday_trash(doc), "ATT-00001")

	# _resolve_attendance_for_workday_trash: resolves attendance from custom_workday link.
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday.frappe.db.get_value",
		return_value="ATT-00002",
	)
	def test_resolve_attendance_for_workday_trash_from_custom_workday(self, _mock_get_value):
		doc = frappe._dict(attendance=None, name="WD-00001", employee="HR-EMP-00001", log_date="2026-06-02")
		self.assertEqual(_resolve_attendance_for_workday_trash(doc), "ATT-00002")


class TestCancelAttendance(FrappeTestCase):
	# cancel_attendance: cancels linked submitted attendance when workday is deleted.
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.db.set_value")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.msgprint")
	@patch("hr_addon.hr_addon.doctype.workday.workday.frappe.get_doc")
	@patch(
		"hr_addon.hr_addon.doctype.workday.workday._resolve_attendance_for_workday_trash",
		return_value="ATT-00001",
	)
	def test_cancel_attendance_cancels_submitted_attendance(
		self, _mock_resolve, mock_get_doc, _mock_msgprint, _mock_set_value
	):
		attendance = MagicMock(docstatus=1, name="ATT-00001")
		mock_get_doc.return_value = attendance
		doc = frappe._dict(name="WD-00001")
		cancel_attendance(doc)
		attendance.cancel.assert_called_once()
