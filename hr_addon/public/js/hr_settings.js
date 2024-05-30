// Copyright (c) 2024, Phamos GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on('HR Settings',  'update_year',  function(frm) {
    console.log('update year')
    frappe.call({
        method: "hr_addon.custom_scripts.custom_python.weekly_working_hours.set_from_to_dates",
        args: {},
        callback(r) {
			if(!r.exc){
				frappe.msgprint("Weekly working hours for permanent employees have been successfully updated.")
				}
			else{
				frappe.msgprint("Error occured while updating weekly working hours")
			}
		}
    });
    
});