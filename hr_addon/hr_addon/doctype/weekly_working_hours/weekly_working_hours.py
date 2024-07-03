# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
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
		self.validate_record()

	def validate_record(self):
		existing_record =  frappe.db.get_value("Weekly Working Hours",
		{
			"employee": self.employee,
			"valid_from": self.valid_from,
			"valid_to":self.valid_to,
			"name": ("!=", self.name),
			"docstatus":1
		}, "name")
		if existing_record :
			frappe.throw(
					_("Weekly Working Hours, already exists for this Employee {0}. Existing record : {1}").format(self.employee,existing_record)
				)
		


