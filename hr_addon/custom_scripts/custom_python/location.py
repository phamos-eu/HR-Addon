import qrcode
import frappe
from frappe.utils import get_url_to_form

def generate_qr_code_for_location(doc, method):
    location_name = doc.name
    # Properly format the URL with the location parameter
    base_url = frappe.utils.get_url()
    qr_code_content = f"{base_url}/app/employee-checkin/new?device_id={location_name}"
    img = qrcode.make(qr_code_content)
    file_name = frappe.generate_hash("", 10)
    file_path = frappe.get_site_path("public", "files", f"{file_name}.png")
    img.save(file_path)

    qr_code_url = f"/files/{file_name}.png"

    # Update the document with the QR code URL
    doc.db_set("qr_code_url", qr_code_url)

    # Attach the QR code to the Location document
    frappe.get_doc({
        "doctype": "File",
        "file_url": qr_code_url,
        "attached_to_name": doc.name,
        "attached_to_doctype": doc.doctype,
        "file_name": f"{location_name}_qr_code.png",
        "folder": "Home/Attachments"
    }).insert()

