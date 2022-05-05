# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname

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

