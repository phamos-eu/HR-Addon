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


	# Validates if a new record's date range overlaps with existing records,
	# and ensures no overlapping days within the same date range for a specific employee.
	def validate_record(self):
		# Check for overlapping date ranges
		existing_records = frappe.db.sql("""
        SELECT wwh.name
        FROM `tabWeekly Working Hours` wwh
        WHERE
            wwh.employee = %s AND
            wwh.docstatus = 1 AND
            wwh.name != %s AND (
                (wwh.valid_from <= %s AND wwh.valid_to >= %s) 
            )
    """, (self.employee, self.name, self.valid_from, self.valid_to))
		print(existing_records)
		# Check for overlapping days
		for existing_record in existing_records:
			print(existing_record[0])
			for day in self.hours:
				existing_record_days = frappe.db.sql("""
                SELECT dhd.day
                FROM `tabDaily Hours Detail` dhd
                WHERE dhd.parent = %s AND dhd.day = %s
            """, (existing_record[0], day.get('day')))
				if existing_record_days:
					frappe.throw(
                    _("Weekly Working Hours already exist for this Employee {0} with overlapping dates and days. </br> Existing Weekly Working Hours : {1}.").format(self.employee,existing_record[0])
                )
                
       
        

            
            

   
    
    
