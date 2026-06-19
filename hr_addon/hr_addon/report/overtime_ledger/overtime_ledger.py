# Copyright (c) 2025, Akhilaminc and contributors
# For license information, please see license.txt

import frappe
import json
from frappe import _
from frappe.desk.reportview import get_filters_cond, get_match_cond
from frappe.utils import cint, flt, get_datetime, getdate, nowdate, add_days
from frappe.query_builder import Order
from frappe.query_builder.functions import CombineDatetime
from frappe.query_builder.functions import Locate
from frappe.query_builder.functions import Sum
from pypika import Case

from hr_addon.events.overtime_ledger import get_reversal_entry_names_from_ole_rows


@frappe.whitelist()
def get_employee_link_filters():
	"""Return link filters for Employee multi-select on this report."""
	return [["Employee", "status", "=", "Active"]]


def validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("{0} is mandatory").format(_("Company")))

	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(
			_("{0} and {1} are mandatory").format(
				frappe.bold(_("From Date")), frappe.bold(_("To Date"))
			)
		)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	columns = get_columns(filters)
	employees = get_employees(filters)
	employee_details = get_employee_details(employees)
	
	precision = cint(frappe.db.get_single_value("System Settings", "float_precision"))
	
	data = []
	
	# Handle Specific Date view - show only one line per employee with balance at end of that date
	if filters.get("specific_date") == 1 and filters.get("from_date"):
		# If no employees selected, get all active employees based on filters
		if not employees:
			employees = get_all_employees_for_range_delta(filters)
			employee_details = get_employee_details(employees)
		
		# Get balance at end of specific date for each employee
		from_date_end = get_datetime(filters.from_date + " 23:59:59")
		
		for employee in employees:
			employee_detail = employee_details.get(employee, {})
			
			# Get balance at end of specific date
			balance_at_date = get_balance_at_date(employee, from_date_end, filters)
			
			# Single row: Balance at end of specific date
			data.append({
				"posting_date": filters.from_date,
				"posting_datetime": get_datetime(filters.from_date + " 23:59:59"),
				"posting_time": None,
				"employee": employee,
				"employee_name": employee_detail.get("employee_name", ""),
				"department": employee_detail.get("department"),
				"in_hour": 0,
				"out_hour": 0,
				"hour_variance": 0,
				"balance_before": balance_at_date,
				"balance_after": balance_at_date,
				"target_hours": None,
				"actual_hours": None,
				"voucher_type": "Balance at Date",
				"voucher_no": "",
				"remarks": "Balance at end of specific date",
				"is_cancelled": 0,
				"company": filters.get("company"),
				"delta": None,
			})
		
		return columns, data
	
	# Handle Range Delta view
	if filters.get("range_delta") == 1 and filters.get("from_date") and filters.get("to_date"):
		# If no employees selected, get all active employees based on filters
		if not employees:
			employees = get_all_employees_for_range_delta(filters)
			employee_details = get_employee_details(employees)
		
		# Get balances at end of from_date and to_date for each employee
		from_date_end = get_datetime(filters.from_date + " 23:59:59")
		to_date_end = get_datetime(filters.to_date + " 23:59:59")
		
		for employee in employees:
			employee_detail = employee_details.get(employee, {})
			
			# Get balance at end of first day (from_date)
			balance_first_day = get_balance_at_date(employee, from_date_end, filters)
			
			# Get balance at end of last day (to_date)
			balance_last_day = get_balance_at_date(employee, to_date_end, filters)
			
			# Calculate delta
			delta = flt(balance_last_day - balance_first_day, precision)
			
			# Row 1: Balance at end of first day
			data.append({
				"posting_date": filters.from_date,
				"posting_datetime": get_datetime(filters.from_date + " 23:59:59"),
				"posting_time": None,
				"employee": employee,
				"employee_name": employee_detail.get("employee_name", ""),
				"department": employee_detail.get("department"),
				"in_hour": 0,
				"out_hour": 0,
				"hour_variance": 0,
				"balance_before": balance_first_day,
				"balance_after": balance_first_day,
				"target_hours": None,
				"actual_hours": None,
				"voucher_type": "Balance End of First Day",
				"voucher_no": "",
				"remarks": "Balance of end of first day",
				"is_cancelled": 0,
				"company": filters.get("company"),
				"delta": None,
			})
			
			# Row 2: Balance at end of last day
			data.append({
				"posting_date": filters.to_date,
				"posting_datetime": get_datetime(filters.to_date + " 23:59:59"),
				"posting_time": None,
				"employee": employee,
				"employee_name": employee_detail.get("employee_name", ""),
				"department": employee_detail.get("department"),
				"in_hour": 0,
				"out_hour": 0,
				"hour_variance": 0,
				"balance_before": balance_last_day,
				"balance_after": balance_last_day,
				"target_hours": None,
				"actual_hours": None,
				"voucher_type": "Balance End of Last Day",
				"voucher_no": "",
				"remarks": "Balance of end of last day",
				"is_cancelled": 0,
				"company": filters.get("company"),
				"delta": delta,
			})
		
		return columns, data
	
	ole_entries = get_overtime_ledger_entries(filters, employees)
	
	opening_rows_added = set()
	reversal_entry_names = get_reversal_entry_names_from_ole_rows(ole_entries)

	for ole in ole_entries:
		employee_detail = employee_details.get(ole.employee, {})
		ole.update(employee_detail)
		
		# Add opening balance row for each employee (once), unless specific_date is enabled
		# Use first OLE's balance_before from DB so opening matches ledger (avoids Sum(hour_variance) vs reversal logic mismatch)
		if not filters.get("specific_date") and ole.employee not in opening_rows_added:
			opening_balance = flt(ole.balance_before, precision)
			data.append({
				"posting_date": filters.from_date,
				"posting_datetime": get_datetime(filters.from_date + " 00:00:00"),
				"posting_time": None,
				"employee": ole.employee,
				"employee_name": ole.employee_name,
				"department": ole.get("department"),
				"in_hour": 0,
				"out_hour": 0,
				"hour_variance": 0,
				"balance_before": opening_balance,
				"balance_after": opening_balance,
				"target_hours": None,
				"actual_hours": None,
				"voucher_type": "Opening",
				"voucher_no": "",
				"remarks": "Opening",
				"is_cancelled": 0,
				"company": ole.get("company"),
			})
			opening_rows_added.add(ole.employee)
		
		is_reversal = ole.name in reversal_entry_names
		
		# Use balance values directly from database (maintained by reposting logic)
		# Target/actual hours: from OLE first; fallback to voucher when OLE has nulls or both zero (missing data)
		target_hours = ole.get("target_hours")
		actual_hours = ole.get("actual_hours")
		need_fallback = (
			(target_hours is None or actual_hours is None)
			or (flt(target_hours) == 0 and flt(actual_hours) == 0 and ole.get("voucher_type") in ("Attendance", "Workday"))
		)
		if need_fallback and ole.get("voucher_type") and ole.get("voucher_no"):
			voucher_hours = get_target_actual_hours_from_voucher(ole.voucher_type, ole.voucher_no)
			if voucher_hours:
				if target_hours is None or (flt(target_hours) == 0 and voucher_hours.get("target_hours") not in (None, 0)):
					target_hours = voucher_hours.get("target_hours")
				if actual_hours is None or (flt(actual_hours) == 0 and voucher_hours.get("actual_hours") not in (None, 0)):
					actual_hours = voucher_hours.get("actual_hours")

		# Default over/under target values from OLE hour_variance (in decimal hours)
		in_hour = max(flt(ole.hour_variance), 0)   # Positive hours
		out_hour = min(flt(ole.hour_variance), 0)  # Negative hours

		# For Overtime Payout vouchers, derive over/under target from the Overtime Payout
		# "hours" Duration field (stored in seconds) and the purpose:
		# - Positive Adjustment -> over target (positive in_hour)
		# - Pay-out / Negative Adjustment -> under target (negative out_hour)
		if ole.get("voucher_type") == "Overtime Payout" and ole.get("voucher_no"):
			op = frappe.get_doc("Overtime Payout", ole.get("voucher_no"))
			hours_seconds = abs(frappe.utils.flt(op.hours or 0))
			hours_decimal = hours_seconds / 3600.0
			if op.purpose == "Positive Adjustment":
				in_hour = hours_decimal
				out_hour = 0
			elif op.purpose in ("Pay-out", "Negative Adjustment"):
				in_hour = 0
				out_hour = -hours_decimal

		# Leave Application: Date column = leave period start (same as Suncycle Work Hour report).
		display_date = None
		if ole.get("voucher_type") == "Leave Application" and ole.get("voucher_no"):
			display_date = get_leave_application_display_date(ole.voucher_no)

		row = frappe._dict({
			"name": ole.name,
			"employee": ole.employee,
			"employee_name": ole.employee_name,
			# Voucher/calendar date (e.g. leave start); ledger order uses posting_datetime from OLE only.
			"posting_date": display_date or ole.posting_date,
			"posting_time": ole.posting_time,
			"posting_datetime": ole.posting_datetime,
			"voucher_type": ole.voucher_type,
			"voucher_no": ole.voucher_no,
			"hour_variance": ole.hour_variance,
			"in_hour": in_hour,
			"out_hour": out_hour,
			"balance_before": flt(ole.balance_before, precision),  # From database
			"balance_after": flt(ole.balance_after, precision),    # From database
			"target_hours": target_hours,
			"actual_hours": actual_hours,
			"remarks": ole.get("remarks"),
			"company": ole.get("company"),
			"department": ole.get("department"),
			"is_cancelled": ole.is_cancelled,
			"voucher_docstatus": ole.get("voucher_docstatus")
		})

		# Display logic: show cancelled entries only when checkbox is checked
		if cint(ole.is_cancelled) == 1 or is_reversal:
			# Show cancelled entries and their reversals only when the checkbox is checked
			if filters.get("show_cancelled_entries"):
				data.append(row)
		else:
			# For regular entries, check voucher status
			if filters.get("show_cancelled_entries") or ole.get("voucher_docstatus") != 2:
				data.append(row)
	
	for row in data:
		# Format target_hours and actual_hours to specified precision
		if row.get("target_hours") is not None:
			row["target_hours"] = flt(row["target_hours"], precision)
		if row.get("actual_hours") is not None:
			row["actual_hours"] = flt(row["actual_hours"], precision)
		# Note: Overtime Payout over/under target is handled via in_hour/out_hour above.

	return columns, data


def get_columns(filters):
	"""Define columns for the report.

	First columns (posting_datetime, employee) are pinned left in the client like Suncycle Work Hours.
	"""
	columns = [
		{
			"label": _("Posting Time"),
			"fieldname": "posting_datetime",
			"fieldtype": "Datetime",
			"width": 180,
			"content": _("Posting Time")
		},
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Data",
			"width": 240,
		},
		{
			"label": _("Voucher Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"label": _("Voucher Type"),
			"fieldname": "voucher_type",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Voucher #"),
			"fieldname": "voucher_no",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Target Hours"),
			"fieldname": "target_hours",
			"fieldtype": "Data",
			"precision": 2,
			"width": 150,
		},
		{
			"label": _("Worked Hours"),
			"fieldname": "actual_hours",
			"fieldtype": "Data",
			"precision": 2,
			"width": 150,
		},
		{
			"label": _("Over Target"),
			"fieldname": "in_hour",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Under Target"),
			"fieldname": "out_hour",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Overtime Balance"),
			"fieldname": "balance_after",
			"fieldtype": "Float",
			"precision": 2,
			"width": 150,
		},
		{
			"label": _("Delta Balance"),
			"fieldname": "delta",
			"fieldtype": "Float",
			"precision": 2,
			"width": 150,
		},
	]
	for col in columns:
		col["sortable"] = False
	return columns


def get_balance_at_date(employee, as_of_datetime, filters):
	"""Get overtime balance for an employee at end of a specific date"""
	OLE = frappe.qb.DocType("Overtime Ledger Entry")
	emp = frappe.qb.DocType("Employee")
	
	query = (
		frappe.qb.from_(OLE)
		.left_join(emp).on(OLE.employee == emp.name)
		.select(OLE.balance_after)
		.where(OLE.employee == employee)
		.where(OLE.posting_datetime <= as_of_datetime)
		.where(OLE.is_cancelled == 0)
		.where(emp.status == "Active")
		.orderby(OLE.posting_datetime, order=Order.desc)
		.orderby(OLE.creation, order=Order.desc)
		.limit(1)
	)
	
	# Apply company filter
	if filters.get("company"):
		query = query.where(OLE.company == filters.get("company"))
	
	result = query.run(as_dict=True)
	
	if result:
		return flt(result[0].balance_after)
	else:
		return 0.0


def get_target_actual_hours_from_voucher(voucher_type, voucher_no):
	"""
	Fetch target_hours and actual_hours from the voucher document when OLE has nulls
	(e.g. legacy OLE entries created before these fields were stored on OLE).
	Supports: Attendance (custom_target_hours, custom_actual_working_hours), Workday (target_hours, actual_working_hours).
	"""
	if not voucher_type or not voucher_no or not frappe.db.exists(voucher_type, voucher_no):
		return {}
	if voucher_type == "Attendance":
		vals = frappe.db.get_value(
			voucher_type, voucher_no,
			["custom_target_hours", "custom_actual_working_hours"],
			as_dict=True
		)
		if vals:
			return {"target_hours": vals.get("custom_target_hours"), "actual_hours": vals.get("custom_actual_working_hours")}
	elif voucher_type == "Workday":
		vals = frappe.db.get_value(
			voucher_type, voucher_no,
			["target_hours", "actual_working_hours"],
			as_dict=True
		)
		if vals:
			return {"target_hours": vals.get("target_hours"), "actual_hours": vals.get("actual_working_hours")}
	return {}


def get_leave_application_display_date(voucher_no):
	"""Leave period start date for OLE rows linked to Leave Application (matches Suncycle Work Hour report)."""
	if not voucher_no or not frappe.db.exists("Leave Application", voucher_no):
		return None
	leave = frappe.db.get_value(
		"Leave Application",
		voucher_no,
		["from_date", "half_day_date", "half_day"],
		as_dict=True,
	)
	if not leave:
		return None
	return getdate(
		leave.half_day_date if (leave.half_day and leave.half_day_date) else leave.from_date
	)


def get_employees(filters):
	"""Get list of employees based on filters"""
	if not filters.get("employee"):
		return []
	
	# Handle MultiSelectList - it comes as a string
	employees = filters.get("employee")
	if isinstance(employees, str):
		import json
		try:
			employees = json.loads(employees)
		except:
			employees = [employees]
	
	return employees


def get_overtime_ledger_entries(filters, employees):
	"""Fetch overtime ledger entries based on filters"""
	if filters.get("specific_date") == 1 and filters.get("from_date"):
		# If specific_date filter is checked, override from_date and to_date to that date
		from_date = get_datetime(filters.from_date + " 00:00:00")
		to_date = get_datetime(filters.from_date + " 23:59:59")
	elif filters.get("range_delta") == 1 and filters.get("from_date") and filters.get("to_date"):
		# If range_delta filter is checked, expand the date range by 30 days on either side
		expanded_from_date = add_days(filters.from_date, -30)
		expanded_to_date = add_days(filters.to_date, 30)
		from_date = get_datetime(expanded_from_date + " 00:00:00")
		to_date = get_datetime(expanded_to_date + " 23:59:59")
	else:	
		from_date = get_datetime(filters.from_date + " 00:00:00")
		to_date = get_datetime(filters.to_date + " 23:59:59")
	
	OLE = frappe.qb.DocType("Overtime Ledger Entry")
	emp = frappe.qb.DocType("Employee")
	
	query = (
		frappe.qb.from_(OLE)
		.left_join(emp).on(OLE.employee == emp.name) 
		.select(
			OLE.name,
			OLE.employee,
			OLE.employee_name,
			OLE.posting_date,
			OLE.posting_time,
			OLE.posting_datetime,
			OLE.hour_variance,
			OLE.balance_before,
			OLE.balance_after,
			OLE.target_hours,
			OLE.actual_hours,
			OLE.voucher_type,
			OLE.voucher_no,
			OLE.remarks,
			OLE.company,
			OLE.department,
			OLE.is_cancelled
		)
		.where(OLE.posting_datetime[from_date:to_date])
		.where(emp.status == "Active")
		.orderby(OLE.posting_datetime)
		.orderby(OLE.creation)
	)

	# Add company filter
	if filters.get("company"):
		query = query.where(OLE.company == filters.get("company"))
	
	# Add employee filter
	if employees:
		query = query.where(OLE.employee.isin(employees))

	
	entries = query.run(as_dict=True) 
	for entry in entries: 
		if entry.voucher_no and entry.voucher_type: 
			voucher_docstatus = frappe.db.get_value(entry.voucher_type, entry.voucher_no, "docstatus") 
			entry.voucher_docstatus = voucher_docstatus or 0
		else:
			entry.voucher_docstatus = 0 	
	
	return entries


def get_opening_balances(filters, employees):
	"""Compute opening balance per employee before the from_date."""
	if not filters or not filters.get("from_date"):
		return {}

	from_date = get_datetime(filters.from_date + " 00:00:00")

	OLE = frappe.qb.DocType("Overtime Ledger Entry")
	emp = frappe.qb.DocType("Employee")

	query = (
		frappe.qb.from_(OLE)
		.left_join(emp).on(OLE.employee == emp.name)
		.select(
			OLE.employee,
			Sum(OLE.hour_variance).as_("opening_balance"),
		)
		.where(OLE.posting_datetime < from_date)
		.where(OLE.is_cancelled == 0)
		.where(emp.status == "Active")
		.groupby(OLE.employee)
	)

	if filters.get("company"):
		query = query.where(OLE.company == filters.get("company"))

	if employees:
		query = query.where(OLE.employee.isin(employees))

	opening_rows = query.run(as_dict=True)
	return {row.employee: flt(row.opening_balance) for row in opening_rows if row.employee}


def get_all_employees_for_range_delta(filters):
	"""Get all active employees based on filters for Range Delta view"""
	Employee = frappe.qb.DocType("Employee")
	
	query = (
		frappe.qb.from_(Employee)
		.select(Employee.name)
		.where(Employee.status == "Active")
	)
	
	# Note: Company filter is not applied here as Employee doesn't have direct company field
	# Company filtering happens at the OLE level in get_balance_at_date
	
	employee_list = query.run(as_dict=True)
	return [emp.name for emp in employee_list]


def get_employee_details(employees):
	"""Get employee details like name, department"""
	if not employees:
		return {}
	
	Employee = frappe.qb.DocType("Employee")
	
	query = (
		frappe.qb.from_(Employee)
		.select(
			Employee.name,
			Employee.employee_name,
			Employee.department
		)
		.where(Employee.name.isin(employees))
	)
	
	employee_list = query.run(as_dict=True)
	
	employee_details = {}
	for emp in employee_list:
		employee_details[emp.name] = {
			"employee_name": emp.employee_name,
			"department": emp.department
		}
	
	return employee_details


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def employee_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	"""Employee search query for MultiSelectList"""

	if isinstance(filters, str):
		filters = json.loads(filters)

	# Use Query Builder
	Employee = frappe.qb.DocType("Employee")
	
	# Build search pattern
	search_pattern = f"%{txt}%"
	
	# Base query
	query = (
		frappe.qb.from_(Employee)
		.select(Employee.name, Employee.employee_name)
		.where(Employee.docstatus < 2)
		.where(Employee.status == "Active")
		.where(
			(Employee.name.like(search_pattern)) | 
			(Employee.employee_name.like(search_pattern))
		)
	)
	
	# Add ordering using LOCATE for relevance
	query = query.orderby(
		Case()
        .when(Locate(txt, Employee.name) > 0, Locate(txt, Employee.name))
        .else_(99999)
	).orderby(
		Case()
        .when(Locate(txt, Employee.employee_name) > 0, Locate(txt, Employee.employee_name))
        .else_(99999)
	).orderby(Employee.name)
	
	# Add limit and offset
	query = query.limit(page_len).offset(start)
	
	return query.run(as_dict=as_dict)
