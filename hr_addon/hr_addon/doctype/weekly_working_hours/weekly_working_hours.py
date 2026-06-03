# Copyright (c) 2022, phamos.eu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt, cint
from frappe.model.naming import make_autoname
from frappe import _
from math import inf

MECHANISM_MINIMUM_BREAK_RULE = "Break Hours from Minimum Break Rule"


class WeeklyWorkingHours(Document):
	def autoname(self):
		Company = frappe.qb.DocType('Company')
		query = (
			frappe.qb.from_(Company)
			.select(Company.abbr)
			.where(Company.name == self.company)
		).run()

		coy = query[0][0] if query else None
		e_name = self.employee
		name_key = coy+'-.YYYY.-'+e_name+'-.####'
		self.name = make_autoname(name_key)
		self.title_hour= self.name

	def validate(self):
		self.validate_if_employee_is_active()
		self.validate_overlapping_records_in_specific_interval()
		self.set_break_hours_if_not_set()

	def _get_rule_break_minutes(self, rules, target_hours):
		for rule_index, rule in enumerate(rules):
			from_hours = flt(rule.from_hours or 0)
			to_hours = flt(rule.to_hours) if rule.to_hours is not None else None

			# Boundary semantics requested:
			# - first row: from_hours <= target_hours <= to_hours
			# - next rows: from_hours < target_hours <= to_hours
			# - open-ended row: target_hours > from_hours (except first row, which is >=)
			in_lower_bound = target_hours >= from_hours if rule_index == 0 else target_hours > from_hours
			in_upper_bound = True if to_hours is None else target_hours <= to_hours
			if in_lower_bound and in_upper_bound:
				return cint(rule.minimum_break_minutes or 0)

		return None

	def set_break_hours_if_not_set(self):
		if not self.hours:
			return

		settings = frappe.get_single("HR Addon Settings")
		if settings.workday_break_calculation_mechanism != MECHANISM_MINIMUM_BREAK_RULE:
			return

		rules = sorted(
			(settings.minimum_break_rule or []),
			key=lambda row: (
				flt(row.from_hours or 0),
				flt(row.to_hours) if row.to_hours is not None else inf,
			),
		)
		if not rules:
			return

		for hour_row in self.hours:
			target_hours = flt(hour_row.hours)
			current_break_minutes = cint(hour_row.break_minutes or 0)
			if target_hours <= 0:
				continue

			required_break_minutes = self._get_rule_break_minutes(rules, target_hours)
			if required_break_minutes is None:
				continue

			if current_break_minutes == 0:
				hour_row.break_minutes = required_break_minutes
				continue

			if current_break_minutes < required_break_minutes:
				# If user enters lower break than the mandatory rule, reset it
				# back to the matched minimum instead of blocking save.
				row_label = hour_row.day or _("Unknown day")
				frappe.msgprint(
					_(
						"Break Minutes for row '{0}' cannot be less than {1} "
						"for target hours {2}."
					).format(row_label, required_break_minutes, target_hours),
					alert=True,
					indicator="orange",
				)
				hour_row.break_minutes = required_break_minutes

	def validate_if_employee_is_active(self):
		if self.employee and frappe.get_value('Employee', self.employee, 'status') != "Active":
			frappe.throw(_("{0} is not active").format(frappe.get_desk_link('Employee', self.employee)))

	def validate_overlapping_records_in_specific_interval(self):

		if not self.valid_from or not self.valid_to:
			frappe.throw("From Date and To Date are required.")

		if not self.employee:
			frappe.throw("Employee required.")

		valid_from = getdate(self.valid_from)
		valid_to = getdate(self.valid_to)

		filters = {"valid_from": valid_from, "valid_to": valid_to, "employee": self.employee}

		wwh = frappe.qb.DocType("Weekly Working Hours")
		overlapping_records = (
			frappe.qb.from_(wwh)
			.select(wwh.name)
			.where(
				(
					(wwh.valid_from <= filters["valid_from"])
					& (wwh.valid_to >= filters["valid_to"])
				)
				| (
					(wwh.valid_from >= filters["valid_from"])
					& (wwh.valid_to <= filters["valid_to"])
				)
			)
			.where(wwh.employee == filters["employee"])
			.where(wwh.docstatus == 1)
		)

		if not self.is_new():
			filters["name"] = self.name
			overlapping_records = overlapping_records.where(wwh.name != filters["name"])

		results = overlapping_records.run(as_dict=True)

		if results:
			overlapping_links = "<br> ".join([frappe.get_desk_link("Weekly Working Hours", d.name) for d in results])
			frappe.throw("Following Weekly Working Hours record already exists for {0} for the specified date range:<br> {1}".format(
				frappe.get_desk_link("Employee", self.employee), overlapping_links))

	def on_submit(self):
		sync_employee_working_hours(self.employee)

	def on_cancel(self):
		clear_employee_working_hours(self.employee)


def _get_latest_submitted_weekly_working_hours(employee):
	entries = frappe.get_all(
		"Weekly Working Hours",
		filters={"employee": employee, "docstatus": 1},
		fields=["name", "total_work_hours"],
		order_by="modified desc",
		limit=1,
	)
	return entries[0] if entries else {}


def sync_employee_working_hours(employee):
	if not employee:
		return

	latest_entry = _get_latest_submitted_weekly_working_hours(employee)
	values = {
		"custom_weekly_working_hours": latest_entry.get("name"),
		"custom_total_work_hours": flt(latest_entry.get("total_work_hours")),
	}
	frappe.db.set_value("Employee", employee, values, update_modified=False)


def clear_employee_working_hours(employee):
	if not employee:
		return

	frappe.db.set_value(
		"Employee",
		employee,
		{
			"custom_weekly_working_hours": None,
			"custom_total_work_hours": 0,
		},
		update_modified=False,
	)


@frappe.whitelist()
def get_latest_submitted_weekly_working_hours_for_employee(employee):
	if not employee:
		return {"weekly_working_hours_entry": None, "total_work_hours": 0}

	latest_entry = _get_latest_submitted_weekly_working_hours(employee)

	return {
		"weekly_working_hours_entry": latest_entry.get("name"),
		"total_work_hours": flt(latest_entry.get("total_work_hours")),
	}


@frappe.whitelist()
def set_from_to_dates():
    # Ensure fiscal year data is present
	FiscalYear = frappe.qb.DocType('Fiscal Year')
	fiscal_year = (
		frappe.qb.from_(FiscalYear)
		.select(FiscalYear.year_start_date ,FiscalYear.year_end_date)
		.where(FiscalYear.disabled == 0)
	).run(as_dict=True)

	if not fiscal_year:
		frappe.throw("No active fiscal year found.")
    
	year_start_date = fiscal_year[0].year_start_date
	year_end_date = fiscal_year[0].year_end_date

	# Update the valid_from and valid_to fields
	wwh = frappe.qb.DocType("Weekly Working Hours")
	Employee = frappe.qb.DocType("Employee")

	subquery = (
		frappe.qb.from_(Employee)
		.select(Employee.name)
		.where(Employee.permanent == 1)
	)

	update_query = (
		frappe.qb.update(wwh)
		.set(wwh.valid_from, year_start_date)
		.set(wwh.valid_to, year_end_date)
		.where(wwh.employee.isin(subquery))
	).run()

	frappe.db.commit()