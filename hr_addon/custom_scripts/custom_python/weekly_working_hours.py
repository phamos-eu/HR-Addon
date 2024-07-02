import frappe
from frappe.utils import today
from frappe.model.document import Document

@frappe.whitelist()
def set_from_to_dates():
    # Ensure fiscal year data is present
    fiscal_year = frappe.db.sql("""
        SELECT year_start_date, year_end_date 
        FROM `tabFiscal Year` 
        WHERE disabled = 0
    """, as_dict=True)
    
    if not fiscal_year:
        frappe.throw("No active fiscal year found.")
    
    year_start_date = fiscal_year[0].year_start_date
    year_end_date = fiscal_year[0].year_end_date

    # Get today's date
    current_date = today()

    # Update the valid_from and valid_to fields
    frappe.db.sql("""
        UPDATE
            `tabWeekly Working Hours`
        SET
            valid_from = %(year_start_date)s,
            valid_to = %(year_end_date)s
        WHERE
            employee IN (
                SELECT
                    name
                FROM
                    `tabEmployee`
                WHERE
                    permanent = 1
            )
            AND creation BETWEEN %(year_start_date)s AND %(year_end_date)s
    """, {
        "year_start_date": year_start_date,
        "year_end_date": year_end_date,
        "current_date": current_date
    })
    
    frappe.db.commit()
