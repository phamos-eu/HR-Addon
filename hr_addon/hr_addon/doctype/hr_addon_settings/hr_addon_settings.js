// Copyright (c) 2022, Jide Olayinka and contributors
// For license information, please see license.txt

frappe.ui.form.on('HR Addon Settings', {
	// refresh: function(frm) {

	// }

	validate: function(frm){
		if (frm.doc.name_of_calendar_export_ics_file.length == 0){
			const randomString = generateRandomString(24);
			frm.set_value("name_of_calendar_export_ics_file", randomString)
		}
	},

	after_save: function(frm){
		if (frm.doc.name_of_calendar_export_ics_file.length < 24){
			frappe.msgprint("The filename is less than 24 characters. Please, consider to have a longer filename or leave it empty to get a random filename.")
		}
	},

	download_ics_file: function(frm){
		frappe.call({
			method: 'hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.download_ics_file',
			callback: function (r) {
				var blob = new Blob([r.message], { type: 'application/octet-stream' });
				var link = document.createElement('a');
				link.href = window.URL.createObjectURL(blob);
				link.download = frm.doc.name_of_calendar_export_ics_file + ".ics";
				link.click();
			}
		});
	},

	generate_workdays_for_past_7_days_now: function(frm){
		frappe.call({
			method: "hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.generate_workdays_for_past_7_days_now",
		}).then(r => {
			frappe.msgprint("The workdays have been generated.")
		})
	}
});

function generateRandomString(length) {
	const characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
	let randomString = '';
	
	for (let i = 0; i < length; i++) {
	  const randomIndex = Math.floor(Math.random() * characters.length);
	  randomString += characters.charAt(randomIndex);
	}
	
	return randomString;
}