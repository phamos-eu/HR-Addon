import qrcode
import frappe
from frappe.utils import get_url_to_form
from frappe import _

@frappe.whitelist()
def validate_duplicate_log(doc, method):
		# Custom SQL query to check existence without using doc.time.date()
    data = frappe.db.sql(
        """
        SELECT
            name as ec
        FROM `tabEmployee Checkin`
        WHERE
            DATE(time) = DATE(%s)
            AND employee = %s
            AND name != %s
            AND log_type = %s
        """,
        (doc.time, doc.employee, doc.name, doc.log_type),
        as_dict=True
    )
    
    # Check if any record was found
    if data and data[0].get('ec'):
        text = "This employee already has a log with the same timestamp" + "</br>"+data[0].get('ec')
        frappe.throw( text)

