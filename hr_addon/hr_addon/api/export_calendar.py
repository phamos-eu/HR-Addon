import io
import frappe
from icalendar import Event, Calendar
from datetime import datetime
from frappe.utils.file_manager import save_file

def generate_leave_ical_file(leave_applications):
    cal = Calendar()

    for leave_application in leave_applications:
        event = Event()

        # Extract data from the Leave Application document
        start_date = leave_application.get('from_date')
        end_date = leave_application.get('to_date')
        employee_name = leave_application.get('employee_name')
        leave_type = leave_application.get('leave_type')
        description = leave_application.get('description')

        event.add('dtstart', start_date)
        event.add('dtend', end_date)
        event.add('summary', f'{employee_name} - {leave_type}')
        event.add('description', description)

        cal.add_component(event)

    # Generate the iCalendar data
    ical_data = cal.to_ical()

    return ical_data

def export_calendar(doc, method=None):
    """
    This function is triggered when a Leave Application is created/changed/updated.
    """
    if doc.status == "Approved":
        leave_applications = frappe.db.get_list("Leave Application", 
                        filters={"status": "Approved"},
                        fields=["from_date", "to_date", "employee_name", "leave_type", "description"])
        ical_data = generate_leave_ical_file(leave_applications)

        # Save the iCalendar data as a File document
        file_name = "Urlaubskalender.ics"  # Set the desired filename here
        create_file(file_name, ical_data, doc.name)


def create_file(file_name, file_content, doc_name):
    """
    Creates a file in public folder.
    """

    file_path = "{}/public/files/{}".format(frappe.utils.get_site_path(), file_name)
    with open(file_path, 'wb') as ical_file:
        ical_file.write(file_content)
