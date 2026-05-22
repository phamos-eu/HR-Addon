# Copyright (c) 2025, Akhilaminc and contributors
# For license information, please see license.txt

import frappe 
from frappe import _ 
from frappe.model.document import Document
from frappe.utils import flt
from frappe.utils import now

class OvertimeLedgerEntry(Document):
	def cancel(self):
		"""
		Cancel Overtime Ledger Entry
		Sets is_cancelled flag, clears links, and triggers balance recalculation
		"""
		# Check if already cancelled
		if self.is_cancelled:
			frappe.msgprint(
				_("Overtime Ledger Entry {0} is already cancelled").format(self.name),
				alert=True,
				indicator="orange"
			)
			return
		
		# Store the voucher details before clearing
		voucher_no = self.voucher_no
		voucher_type = self.voucher_type
		
		# Set is_cancelled flag using db_set (more efficient than save)
		self.db_set('is_cancelled', 1, update_modified=True)
		
		# Clear the voucher_no link to allow deletion of linked documents
		# This clears the Dynamic Link that would prevent Attendance deletion
		if voucher_no:
			self.db_set('voucher_no', None, update_modified=False)
			
			# Also clear the link from Attendance side
			if voucher_type == "Attendance" and frappe.db.exists("Attendance", voucher_no):
				frappe.db.set_value(
					"Attendance",
					voucher_no,
					"custom_overtime_ledger_entry",
					None,
					update_modified=False
				)
		
		# Commit changes to database
		frappe.db.commit()
		
		# Show success message
		frappe.msgprint(
			_("Overtime Ledger Entry {0} has been cancelled successfully").format(self.name),
			alert=True,
			indicator="red"
		)
		
		# Trigger balance recalculation for future entries
		self.repost_future_entries()
		
		# Show info about reposting
		frappe.msgprint(
			_("Balance recalculation has been queued for all future entries"),
			alert=True,
			indicator="blue"
		) 

	def validate(self):
		"""Set posting_datetime and calculate balances"""
		from frappe.utils import get_time, getdate, formatdate

		# fetch_from does not run on programmatic insert; set for reports and list views
		if self.employee and not self.get("employee_name"):
			self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")

		# Set posting_datetime from posting_date and posting_time
		if not self.posting_datetime and self.posting_date:
			# Extract just the date part (YYYY-MM-DD) in case posting_date is a datetime
			posting_date_str = str(getdate(self.posting_date))
			# Extract just the time component (HH:MM:SS) even if posting_time is a datetime
			if self.posting_time:
				time_obj = get_time(self.posting_time)
				posting_time_str = str(time_obj)
			else:
				posting_time_str = "00:00:00"
			# Combine date and time into datetime string
			self.posting_datetime = f"{posting_date_str} {posting_time_str}"

		# Require Overtime Hours Frozen Upto in HR Addon Settings
		if self.posting_date:
			settings = frappe.get_single("HR Addon Settings")
			overtime_frozen = getattr(settings, "overtime_frozen", None)
			if not overtime_frozen:
				frappe.throw(
					_("Please set Overtime Hours Frozen Upto in HR Addon Settings (Overtime Ledger tab) before creating or modifying Overtime Ledger entries."),
					title=_("Overtime Frozen Date Required"),
				)
			if getdate(self.posting_date) <= getdate(overtime_frozen):
				frappe.throw(
					_("Overtime Ledger entries on or before {0} are frozen. You cannot create or modify entries in the closed period.").format(
						formatdate(overtime_frozen)
					),
					title=_("Overtime Frozen"),
				)

		# Calculate balances for new entries
		if self.is_new():
			self.calculate_balance()
		else:
			# Prevent modification of balance fields after creation
			# Only cancellation should trigger balance changes
			if not self.is_cancelled:
				doc_before = self.get_doc_before_save()
				if doc_before:
					# Check if balance fields were changed
					if (self.balance_before != doc_before.balance_before or 
						self.balance_after != doc_before.balance_after):
						frappe.throw(
							_("Cannot modify balance fields of submitted Overtime Ledger Entry. "
							  "Balance Before: {0}, Balance After: {1}").format(
								doc_before.balance_before, doc_before.balance_after
							)
						)
	
	def on_update_after_submit(self):
		"""Handle updates after document is submitted (like cancellation)"""
		# DISABLED: Do not trigger repost when marking as cancelled
		# The reversal entry maintains the balance chain correctly
		# Reposting is only needed for backdated entries (handled in after_insert hook)
		pass
	
	def calculate_balance(self):
		"""Calculate balance_before and balance_after for this entry"""
		from hr_addon.events.overtime_ledger import get_previous_balance
		from frappe.utils import get_time, getdate
		
		
		# Ensure posting_datetime is set
		if not self.posting_datetime:
			# Extract just the date part (YYYY-MM-DD)
			posting_date_str = str(getdate(self.posting_date))
			# Extract just the time component (HH:MM:SS)
			if self.posting_time:
				time_obj = get_time(self.posting_time)
				posting_time_str = str(time_obj)
			else:
				posting_time_str = "00:00:00"
			self.posting_datetime = f"{posting_date_str} {posting_time_str}"
		
		
		# Get previous balance
		previous_balance = get_previous_balance(self.employee, self.posting_datetime)
		
		
		# Calculate new balances
		self.balance_before = flt(previous_balance)
		self.balance_after = flt(previous_balance) + flt(self.hour_variance)
		
	
	def repost_future_entries(self):
		"""Trigger recalculation for all entries after this one. Respects Overtime Hours Frozen Upto (repost only after that date)."""
		from hr_addon.events.overtime_ledger import update_entries_after
		from frappe.utils import add_days, getdate

		if not self.posting_datetime:
			return

		effective_date = self.posting_date
		effective_time = self.posting_time or "00:00:00"

		settings = frappe.get_single("HR Addon Settings")
		overtime_frozen = getattr(settings, "overtime_frozen", None)
		if overtime_frozen:
			day_after_frozen = add_days(getdate(overtime_frozen), 1)
			if getdate(self.posting_date) < day_after_frozen:
				effective_date = day_after_frozen
				effective_time = "00:00:00"

		frappe.enqueue(
			update_entries_after,
			employee=self.employee,
			posting_date=effective_date,
			posting_time=effective_time,
			queue="short",
			timeout=300,
		)



# ============================================================================
# MODULE-LEVEL HELPER FUNCTIONS FOR overtime pay-out
# ============================================================================

def make_ole_entry(args):
	"""
	Create Overtime Ledger Entry
	Following make_entry() pattern from erpnext.stock.stock_ledger
	
	This is called by Overtime Pay-out (and other vouchers) to create OLE
	Similar to how Stock Entry calls make_entry() to create Stock Ledger Entry
	
	Args:
		args: Dictionary with OLE fields
		
	Returns:
		OLE document
	"""
	
	args["doctype"] = "Overtime Ledger Entry"
	ole = frappe.get_doc(args)
	ole.flags.ignore_permissions = 1
	
	ole.insert()
	
	frappe.logger().debug(f"make_ole_entry: Created OLE {ole.name}, balance: {ole.balance_before} -> {ole.balance_after}")
	
	return ole


def set_ole_as_cancel(voucher_type, voucher_no):
	"""
	Mark Overtime Ledger Entries as cancelled for a specific voucher
	Following set_as_cancel() pattern from erpnext.stock.stock_ledger
	
	This is called when an Overtime Payout (or other voucher) is cancelled
	Sets is_cancelled=1 on all OLE entries for that voucher
	
	Note: This only MARKS entries as cancelled. A separate reversal entry
	will be created to maintain the balance chain.
	
	Args:
		voucher_type: Document type (e.g., "Overtime Payout")
		voucher_no: Document name
	"""
	
	# Use Query Builder for UPDATE
	OLE = frappe.qb.DocType("Overtime Ledger Entry")
	
	result = (
		frappe.qb.update(OLE)
		.set(OLE.is_cancelled, 1)
		.set(OLE.modified, now())
		.set(OLE.modified_by, frappe.session.user)
		.where(OLE.voucher_type == voucher_type)
		.where(OLE.voucher_no == voucher_no)
		.where(OLE.is_cancelled == 0)
	).run()
	
	frappe.logger().debug(f"set_ole_as_cancel: Updated {result} rows")
	
	frappe.db.commit()
	
	# Note: We do NOT trigger reposting here
	# The reversal entry will be created separately and will maintain the balance chain


def make_ole_entries(ole_entries):
	"""
	Create or cancel multiple Overtime Ledger Entries
	Following make_sl_entries() pattern from erpnext.stock.stock_ledger
	
	This is the main entry point for creating/cancelling OLE entries
	Called by Overtime Pay-out and other vouchers
	
	Args:
		ole_entries: List of OLE entry dictionaries
	"""
	if not ole_entries:
		return
	
	cancel = ole_entries[0].get("is_cancelled")
	
	if cancel:
		# Mark existing entries as cancelled
		set_ole_as_cancel(
			ole_entries[0].get("voucher_type"),
			ole_entries[0].get("voucher_no")
		)
	
	# Create OLE entries
	for ole in ole_entries:
		if ole.get("hour_variance") or cancel:
			ole_doc = make_ole_entry(ole)			