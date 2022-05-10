// Copyright (c) 2022, Jide Olayinka and contributors
// For license information, please see license.txt

frappe.ui.form.on('Workday', {
	// refresh: function(frm) {

	// }
	setup: function(frm){
		frm.set_query("attendance",function(){
			
			return{
				"filters":[
					['Attendance','employee','=',frm.doc.employee],
					['Attendance','attendance_date','=',frm.doc.log_date]
				]
			};
		});
	},
	attendance: function(frm){
		//console.log(frm.doc);
		let aemployee = frm.doc.employee;
		let adate = frm.doc.log_date;
		if(aemployee){
			frappe.call({
				method:'hr_addon.hr_addon.api.utils.view_actual_employee_log',
				args:{aemployee:aemployee,adate:adate}
			}).done((r)=>{
				frm.doc.employee_checkins = [];
				let alog = r.message;
				console.log(alog);
				frm.set_value("hours_worked",(alog[0].ahour/3600).toFixed(2));
				frm.set_value("break_hours",(alog[0].bhour/3600).toFixed(2));
				frm.set_value("target_hours",alog[0].thour);
				$.each(alog[0].items,function(i,e){
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
