frappe.ui.form.on('Employee Checkin', {
    onload(frm) {
        if (frm.is_new()) {
            frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name", function(value) {
                if (value) {
                    frm.set_value('employee', value.name);
                }
            });
        }

        const hasHRRole = frappe.user.has_role("HR User") || frappe.user.has_role("HR Manager");
        if (!hasHRRole) {
            frm.set_df_property('device_id', 'hidden', 1);
        }
    }
});
