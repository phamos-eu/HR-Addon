# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate
from frappe.model.naming import make_autoname
from frappe import _, bold

class WeeklyWorkingHours(Document):
	#pass
	def autoname(self):
		""""""
		coy = frappe.db.sql("select abbr from tabCompany where name=%s", self.company)[0][0]
		e_name = self.employee
		#name_key = coy+'-.YYYY.-'+e_name
		name_key = coy+'-.YYYY.-'+e_name+'-.####'
		self.name = make_autoname(name_key)
		self.title_hour= self.name

	def validate(self):
		self.validate_if_employee_is_active()
		self.validate_overlapping_records_in_specific_interval()

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

		condition = ""
		if not self.is_new():
			condition += "AND name != %(name)s "
			filters["name"] = self.name

		overlapping_records = frappe.db.sql("""
			SELECT name 
			FROM `tabWeekly Working Hours`
			WHERE 
				(
					(valid_from <= %(valid_from)s AND valid_to >= %(valid_to)s) OR
					(valid_from <= %(valid_from)s AND valid_to >= %(valid_to)s) OR
					(valid_from >= %(valid_from)s AND valid_to <= %(valid_to)s)
				) AND employee = %(employee)s AND docstatus = 1 {condition}
			""".format(condition=condition), filters, as_dict=True)

		if overlapping_records:
			overlapping_records = "<br> ".join([frappe.get_desk_link("Weekly Working Hours", d.name) for d in overlapping_records])
			frappe.throw("Following Weekly Working Hours record already exists for {0} for the specified date range:<br> {1}".format(frappe.get_desk_link("Employee", self.employee), overlapping_records))
