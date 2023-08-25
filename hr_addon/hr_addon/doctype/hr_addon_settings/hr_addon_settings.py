# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

import frappe, os
from frappe.model.document import Document

class HRAddonSettings(Document):
	def before_save(self):
		# remove the old ics file
		old_doc = self.get_doc_before_save()
		old_file_name = old_doc.name_of_calendar_export_ics_file
		if old_file_name != self.name_of_calendar_export_ics_file:
			os.remove("{}/public/files/{}.ics".format(frappe.utils.get_site_path(), old_file_name))

		# remove also the Urlaubskalender.ics, if exist
		if os.path.exists("{}/public/files/Urlaubskalender.ics".format(frappe.utils.get_site_path())):
			os.remove("{}/public/files/Urlaubskalender.ics".format(frappe.utils.get_site_path()))