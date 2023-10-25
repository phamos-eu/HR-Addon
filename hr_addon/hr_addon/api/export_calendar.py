import io, os
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
        end_date += frappe.utils.datetime.timedelta(days=1)
        employee_name = leave_application.get('employee_name')
        leave_type = leave_application.get('leave_type')
        description = leave_application.get('description')
        if not description:
            description = ""

        uid = leave_application.name
        if uid.count("-") == 4 and uid.find("CANCELLED") < 0:
            uid = uid[:-2]

        event.add('dtstart', start_date)
        event.add('dtend', end_date)
        summary = ""
        if leave_application.get("cancelled"):
            summary = "CANCELLED - "
        event.add('summary', f'{summary}{employee_name} - {leave_type}')
        event.add('description', description)
        event.add("uid", uid)

        cal.add_component(event)

    # Generate the iCalendar data
    ical_data = cal.to_ical()

    return ical_data

def export_calendar(doc, method=None):
    """
    This function is triggered when a Leave Application is created/changed/updated.
    """
    if doc.status == "Approved" or doc.status == "Cancelled":
        leave_applications = frappe.db.get_list("Leave Application", 
                        filters=[["status", "in", ["Approved", "Cancelled"]]],
                        fields=["name", "status", "from_date", "to_date", "employee_name", "leave_type", "description", "amended_from"])

        index = 0
        for la in leave_applications:
            if la["status"] == "Cancelled":
                la["cancelled"] = False
                if la["name"] in [app["amended_from"] for app in leave_applications]:
                    del leave_applications[index]
                else:
                    la["cancelled"] = True
            index = index + 1

        ical_data = generate_leave_ical_file(leave_applications)

        # Save the iCalendar data as a File document
        file_name = frappe.db.get_single_value("HR Addon Settings", "name_of_calendar_export_ics_file")
        file_name = "{}.ics".format(file_name)  # Set the desired filename here
        create_file(file_name, ical_data, doc.name)


def create_file(file_name, file_content, doc_name):
    """
    Creates a file in user defined folder
    """
    folder_path = frappe.db.get_single_value("HR Addon Settings", "ics_folder_path")
    if not folder_path:
        folder_path = "{}/public/files/".format(frappe.utils.get_site_path())
    file_path = os.path.join(folder_path, file_name)
    with open(file_path, 'wb') as ical_file:
        ical_file.write(file_content)
