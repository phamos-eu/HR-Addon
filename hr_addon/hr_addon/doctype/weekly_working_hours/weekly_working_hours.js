// Copyright (c) 2022, Jide Olayinka and contributors
// For license information, please see license.txt

frappe.ui.form.on('Weekly Working Hours', {
	// refresh: function(frm) {

	// }
});

frappe.ui.form.on('Daily Hours Detail',{
	//
	hours: function(frm, cdt, cdn){
		//
		//console.log('Hourly edit');
		var total_hour = 0;
		var t_hour_time = 0;
		
		$.each(frm.doc.hours|| [], function(i,d){
			total_hour += flt(d.hours);
			t_hour_time += flt(d.hours)*60;
		});
		frm.set_value("total_work_hours",total_hour);
		frm.set_value("total_hours_time",t_hour_time);
		//this.frm.refresh_fields();
	},
});