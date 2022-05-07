// Copyright (c) 2022, Jide Olayinka and contributors
// For license information, please see license.txt

frappe.ui.form.on('Workday', {
	// refresh: function(frm) {

	// }
	setup: function(frm){
		frm.set_query("attendance",function(){
			return{
				"filters": [['Attendance','employee','=',frm.doc.employee]]
			};
		});
	},
	attendance: function(frm){
		//console.log(frm.doc);
		let atdc = frm.doc.attendance;
		if(atdc){
			frappe.call({
				method:'hr_addon.hr_addon.api.utils.get_employee_checkin',
				args:{attendance:atdc}
			}).done((r)=>{
				frm.doc.employee_checkins = [];
				$.each(r.message,function(i,e){
					let nw_checkins = frm.add_child("employee_checkins");
					nw_checkins.employee_checkin = e.name;
					nw_checkins.log_type = e.log_type;
					nw_checkins.log_time = e.time;
					nw_checkins.skip_auto_attendance= e.skip_auto_attendance;

				});
				refresh_field("employee_checkins");
			});
			
		}
	}
});
