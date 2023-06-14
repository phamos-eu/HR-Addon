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
		/* frm.set_query('Employee Checkins','employee_checkins', function(){
			return{
				'filters':[
					['employee_checkins','employee_checkin','=',frm.doc.attendance]
					
				],
			};
		}); */
	},
	/* onload: function(frm){
		frm.set_query('Employee Checkins','employee_checkins', function(){
			return{
				'filters':{
					'employee_checkin':['=',frm.attendance]
				}
			};
		});
	}, */

	attendance: function(frm){
		get_hours(frm)
	},

	log_date: function(frm){
		frappe.call({
			method: "hr_addon.hr_addon.doctype.workday.workday.date_is_in_holiday_list",
			args: {
				employee: frm.doc.employee,
				date: frm.doc.log_date
			},
			callback: function(r){
				if (r.message == true){
					frm.set_value("hours_worked", 0)
					frm.set_value("break_hours", 0)
					frm.set_value("total_work_seconds", 0)
					frm.set_value("total_break_seconds", 0)
					frm.set_value("target_hours", 0)
					frm.set_value("total_target_seconds", 0)
					frm.set_value("expected_break_hours", 0)
					frm.set_value("actual_working_hours", 0)
					frm.set_value("employee_checkins", [])
					frm.set_value("first_checkin", "")
					frm.set_value("last_checkout", "")
				} else {
					get_hours(frm)
				}
			}
		})
	}
});

var get_hours = function(frm){
	let aemployee = frm.doc.employee;
	let adate = frm.doc.log_date;
	if(aemployee){
		frappe.call({
			method:'hr_addon.hr_addon.api.utils.view_actual_employee_log',
			args:{aemployee:aemployee,adate:adate}
		}).done((r)=>{
			frm.doc.employee_checkins = [];
			let alog = r.message;
			frm.set_value("hours_worked",(alog[0].ahour/(60*60)).toFixed(2));
			frm.set_value("break_hours",(alog[0].bhour/(60*60)).toFixed(2));
			frm.set_value("total_work_seconds",(alog[0].ahour).toFixed(2));
			frm.set_value("total_break_seconds",(alog[0].bhour).toFixed(2));
			frm.set_value("target_hours",alog[0].thour);
			frm.set_value("total_target_seconds",(alog[0].thour*(60*60)));
			frm.set_value("expected_break_hours",(alog[0].break_minutes/60));
			frm.set_value("actual_working_hours",frm.doc.hours_worked - frm.doc.expected_break_hours);
			let ec = alog[0].items
			frm.set_value("first_checkin",ec[0].time);
			frm.set_value("last_checkout",ec[ec.length-1].time);
			$.each(ec,function(i,e){
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