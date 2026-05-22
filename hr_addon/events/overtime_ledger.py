import frappe
from frappe import _
from frappe.utils import now, flt, get_time, getdate, cint
from frappe.query_builder import Order
from frappe.query_builder.functions import Count

# Written by reverse_attendance_overtime_ledger_entry, reverse_workday_leave_ole, etc.
REVERSAL_REMARK_MARKER = "Reversal of"


def is_overtime_ledger_enabled():
	"""Master switch from HR Addon Settings (Overtime Ledger tab)."""
	return cint(frappe.db.get_single_value("HR Addon Settings", "enable_overtime_ledger_feature"))


def require_overtime_ledger_enabled(message=None):
	"""Raise when overtime ledger is disabled (submit / manual create paths)."""
	if not is_overtime_ledger_enabled():
		frappe.throw(
			message
			or _("Enable Overtime Ledger Feature in HR Addon Settings before using overtime ledger.")
		)


def is_reversal_ledger_row(remarks):
	"""True if remarks match explicit reversal rows (English marker from reverse_* helpers)."""
	return bool(remarks and REVERSAL_REMARK_MARKER in str(remarks))


def get_reversal_entry_names_from_ole_rows(entries):
	"""Names of OLE rows that net-cancel cancelled rows on the same voucher (reversals).

	- Primary: remarks contain REVERSAL_REMARK_MARKER (works for Attendance / new Leave reversals).
	- Fallback: active row's hour_variance sums to zero with all cancelled rows on that voucher
	  (legacy reversals with translated remarks). A later legitimate OLE on the same voucher_no
	  (e.g. resubmitted attendance) does not match the cancelled sum and is not treated as reversal.
	"""
	by_v = {}
	for e in entries:
		vn = e.get("voucher_no")
		if not vn:
			continue
		by_v.setdefault(vn, []).append(e)

	out = set()
	for _vn, group in by_v.items():
		cancelled = [x for x in group if cint(x.get("is_cancelled")) == 1]
		active = [x for x in group if cint(x.get("is_cancelled")) == 0]
		if not cancelled or not active:
			continue
		csum = sum(flt(x.get("hour_variance")) for x in cancelled)
		for e in active:
			if is_reversal_ledger_row(e.get("remarks")):
				out.add(e.get("name"))
				continue
			if abs(flt(e.get("hour_variance")) + csum) < 1e-6:
				out.add(e.get("name"))
	return out


def after_insert_overtime_ledger_entry(doc, method=None):
	"""
	After inserting Overtime Ledger Entry - Check if reposting is needed
	
	If this is a backdated entry (posting_datetime is earlier than latest entry),
	trigger reposting of all future entries to recalculate their balances.
	
	This is called on after_insert hook
	"""
	if not is_overtime_ledger_enabled() and not is_reversal_ledger_row(doc.remarks):
		return

	# Check if there are entries AFTER this one that need reposting
	OLE = frappe.qb.DocType("Overtime Ledger Entry")
	
	future_entries_count = (
		frappe.qb.from_(OLE)
		.select(Count(OLE.name))
		.where(OLE.employee == doc.employee)
		.where(OLE.posting_datetime > doc.posting_datetime)
		.where(OLE.is_cancelled == 0)
		.where(OLE.name != doc.name)
	).run()[0][0]
	
	# If there are future entries, this is a backdated entry - trigger reposting
	if future_entries_count > 0:
		frappe.msgprint(
			_("Backdated entry detected. Recalculating balances for {0} future entries...").format(
				future_entries_count
			),
			alert=True,
			indicator="blue"
		)
		
		# Run reposting immediately (not in background) to ensure it completes
		# Background workers might not be running in development
		try:
			update_entries_after(
				employee=doc.employee,
				posting_date=doc.posting_date,
				posting_time=doc.posting_time or "00:00:00"
			)
			frappe.msgprint(
				_("Balance recalculation completed successfully"),
				alert=True,
				indicator="green"
			)
		except Exception as e:
			frappe.log_error(title="Overtime Repost Failed", message=str(e))
			frappe.msgprint(
				_("Warning: Balance recalculation failed. Please trigger manual repost."),
				alert=True,
				indicator="orange"
			)
	
	# Always update the employee's current overtime balance
	update_employee_overtime_balance(doc.employee)

def update_employee_overtime_balance(employee): 
	"""
	Update the current overtime balance stored in Employee document
	"""
	# Clear cache before reading to ensure fresh data
	frappe.clear_cache(doctype="Overtime Ledger Entry")
	
	balance_info = get_employee_overtime_balance(employee)
	
	frappe.db.set_value("Employee", employee, "custom_current_overtime_hours", balance_info.get("balance"), update_modified=False)
	frappe.db.set_value("Employee", employee, "custom_overtime_ledger_entry", balance_info.get("last_entry"), update_modified=False)
	frappe.db.commit()
	


def get_previous_balance(employee, before_datetime):
	"""
	Get the last overtime balance for an employee before a specific datetime
	Similar to get_previous_sle in Stock Ledger
	
	Excludes cancelled AND reversal entries to get the correct running balance
	
	Args:
		employee: Employee ID
		before_datetime: Get balance before this datetime (can be string or datetime)
	
	Returns:
		Float: The balance_after from the last entry, or 0.0 if no previous entries
	"""
	# Ensure before_datetime is a clean string without timezone
	if not isinstance(before_datetime, str):
		before_datetime = str(before_datetime)
	
	# Clean any timezone info (e.g., '2025-12-01 17:00:00-01:00' -> '2025-12-01 17:00:00')
	if '+' in before_datetime or (before_datetime.count('-') > 2):
		# Split on + or last - to remove timezone
		before_datetime = before_datetime.split('+')[0].split()[0] + ' ' + before_datetime.split()[1] if len(before_datetime.split()) > 1 else before_datetime.split('+')[0]
		before_datetime = before_datetime.strip()
	
	# Use Query Builder
	OLE = frappe.qb.DocType("Overtime Ledger Entry")
	
	# Include cancelled rows so reversal classification can pair active reversals with them
	all_entries = (
		frappe.qb.from_(OLE)
		.select(
			OLE.name,
			OLE.balance_after,
			OLE.posting_datetime,
			OLE.remarks,
			OLE.is_cancelled,
			OLE.voucher_no,
			OLE.hour_variance,
		)
		.where(OLE.employee == employee)
		.where(OLE.posting_datetime < before_datetime)
		.orderby(OLE.posting_datetime, order=Order.desc)
		.orderby(OLE.creation, order=Order.desc)
	).run(as_dict=True)
	
	if not all_entries:
		return 0.0
	
	reversal_names = get_reversal_entry_names_from_ole_rows(all_entries)

	for entry in all_entries:
		if cint(entry.is_cancelled):
			continue
		if entry.name in reversal_names:
			continue
		return flt(entry.balance_after)
	return 0.0


def update_entries_after(employee, posting_date, posting_time=None):
	"""
	Recalculate balances for all overtime ledger entries after a specific date/time.
	Respects HR Addon Settings "Overtime Hours Frozen Upto": repost only from after that date.

	Args:
		employee: Employee ID
		posting_date: Date to start recalculation from
		posting_time: Time to start recalculation from (optional)
	"""
	from frappe.utils import add_days

	posting_date_str = str(getdate(posting_date))
	if posting_time:
		time_obj = get_time(posting_time)
		posting_time_str = str(time_obj)
	else:
		posting_time_str = "00:00:00"

	posting_datetime = f"{posting_date_str} {posting_time_str}"

	settings = frappe.get_single("HR Addon Settings")
	overtime_frozen = getattr(settings, "overtime_frozen", None)
	if overtime_frozen:
		day_after_frozen = add_days(getdate(overtime_frozen), 1)
		frozen_cutoff = f"{day_after_frozen} 00:00:00"
		if posting_datetime < frozen_cutoff:
			posting_date_str = str(day_after_frozen)
			posting_time_str = "00:00:00"
			posting_datetime = frozen_cutoff

	updater = UpdateOvertimeBalanceAfter(employee, posting_datetime)
	updater.build()


class UpdateOvertimeBalanceAfter:
	"""
	Recalculate overtime balances after a transaction
	Similar to update_entries_after class in Stock Ledger
	
	This class:
	1. Gets all entries from a specific datetime onwards
	2. Calculates running balance for each entry
	3. Updates balance_before and balance_after fields
	"""
	
	def __init__(self, employee, posting_datetime):
		self.employee = employee
		self.posting_datetime = posting_datetime
		self.entries = []
	
	def build(self):
		"""Main method to recalculate balances"""
		# Get all entries that need recalculation
		self.get_entries_to_recalculate()
		
		# Calculate and update balances
		self.recalculate_balances()
		
		# Ensure all updates are committed before reading for employee balance
		frappe.db.commit()
		
		# Clear any cached queries to ensure fresh data
		frappe.db.sql("SELECT 1")
		
		# Update the employee's current overtime balance after reposting
		update_employee_overtime_balance(self.employee)
	
	def _entries_before_posting_datetime(self):
		OLE = frappe.qb.DocType("Overtime Ledger Entry")
		return (
			frappe.qb.from_(OLE)
			.select(OLE.name, OLE.hour_variance, OLE.voucher_no, OLE.is_cancelled, OLE.remarks)
			.where(OLE.employee == self.employee)
			.where(OLE.posting_datetime < self.posting_datetime)
			.orderby(OLE.posting_datetime, order=Order.asc)
			.orderby(OLE.creation, order=Order.asc)
		).run(as_dict=True)

	def calculate_opening_balance(self, all_before=None):
		"""Calculate the correct opening balance before the first entry by recalculating from scratch"""
		if all_before is None:
			all_before = self._entries_before_posting_datetime()
		if not all_before:
			return 0.0
		reversal_names = get_reversal_entry_names_from_ole_rows(all_before)
		balance = 0.0
		for entry in all_before:
			if entry.is_cancelled == 1:
				continue
			if entry.name in reversal_names:
				continue
			balance = balance + flt(entry.hour_variance)
		return balance
	
	def get_entries_to_recalculate(self):
		"""Get all overtime ledger entries from posting_datetime onwards"""
		# Use Query Builder
		OLE = frappe.qb.DocType("Overtime Ledger Entry")
		
		self.entries = (
			frappe.qb.from_(OLE)
			.select(OLE.name, OLE.hour_variance, OLE.posting_datetime, OLE.voucher_no, 
					OLE.voucher_type, OLE.is_cancelled, OLE.remarks, OLE.balance_after)
			.where(OLE.employee == self.employee)
			.where(OLE.posting_datetime >= self.posting_datetime)
			.orderby(OLE.posting_datetime, order=Order.asc)
			.orderby(OLE.creation, order=Order.asc)
		).run(as_dict=True)
	
	def recalculate_balances(self):
		"""Calculate running balance for each entry and update (matches report logic)"""
		if not self.entries:
			return
		
		all_before = self._entries_before_posting_datetime()
		current_balance = self.calculate_opening_balance(all_before)
		seen = {e["name"] for e in all_before}
		combined = list(all_before)
		for e in self.entries:
			if e["name"] not in seen:
				seen.add(e["name"])
				combined.append(e)
		reversal_names = get_reversal_entry_names_from_ole_rows(combined)
		OLE = frappe.qb.DocType("Overtime Ledger Entry")
		# Process each entry
		for entry in self.entries:
			is_reversal = entry.name in reversal_names
			is_cancelled = entry.is_cancelled == 1
			
			balance_before = current_balance
			
			# Only update running balance for non-cancelled, non-reversal entries
			if not is_cancelled and not is_reversal:
				current_balance = current_balance + flt(entry.hour_variance)
			
			# For ALL entries, set balance_after to current running balance
			# Cancelled and reversal entries will show the "skipped" balance
			balance_after = current_balance
			
			# Update the entry with new balances
			(
				frappe.qb.update(OLE)
				.set(OLE.balance_before, balance_before)
				.set(OLE.balance_after, balance_after)
				.set(OLE.modified, now())
				.where(OLE.name == entry.name)
			).run()
			
			# Commit after each update to ensure subsequent queries read the updated values
			frappe.db.commit()


def calculate_overtime_balance(ole_doc):
	"""
	Calculate balance_before and balance_after for an Overtime Ledger Entry document
	Called before submit
	
	Args:
		ole_doc: Overtime Ledger Entry document
	"""
	# Set posting_datetime if not set
	if not ole_doc.posting_datetime:
		# Extract just the date part (YYYY-MM-DD)
		posting_date_str = str(getdate(ole_doc.posting_date))
		# Extract just the time component (HH:MM:SS)
		if ole_doc.posting_time:
			time_obj = get_time(ole_doc.posting_time)
			posting_time_str = str(time_obj)
		else:
			posting_time_str = "00:00:00"
		ole_doc.posting_datetime = f"{posting_date_str} {posting_time_str}"
	
	# Get previous balance
	previous_balance = get_previous_balance(ole_doc.employee, ole_doc.posting_datetime)
	
	# Calculate new balances
	ole_doc.balance_before = previous_balance
	ole_doc.balance_after = previous_balance + flt(ole_doc.hour_variance)


@frappe.whitelist()
def get_employee_overtime_balance(employee, as_of_date=None):
	"""
	Get current or historical overtime balance for an employee
	
	Args:
		employee: Employee ID
		as_of_date: Optional date to get historical balance (format: YYYY-MM-DD)
	
	Returns:
		dict: {
			"employee": employee,
			"balance": float,
			"as_of_date": date,
			"last_entry": entry_name
		}
	"""
	if as_of_date:
		as_of_datetime = f"{as_of_date} 23:59:59"
	else:
		# Get current datetime as string (YYYY-MM-DD HH:MM:SS)
		now_str = now()
		# Clean any timezone info
		if '+' in now_str or (now_str.count('-') > 2):
			now_str = now_str.split('+')[0].strip()
		as_of_datetime = now_str
	
	# Use Query Builder
	OLE = frappe.qb.DocType("Overtime Ledger Entry")

	# Get latest active OLE entry for this employee
	# Trust the is_cancelled flag - don't filter by voucher type or voucher status
	# This ensures consistency with Employee record updates
	last_entry = (
		frappe.qb.from_(OLE)
		.select(OLE.name, OLE.balance_after, OLE.posting_datetime)
		.where(OLE.employee == employee)
		.where(OLE.posting_datetime <= as_of_datetime)
		.where(OLE.is_cancelled == 0)
		.orderby(OLE.posting_datetime, order=Order.desc)
		.orderby(OLE.creation, order=Order.desc)
		.limit(1)
	).run(as_dict=True)
	
	if last_entry:
		return {
			"employee": employee,
			"balance": flt(last_entry[0].balance_after),
			"as_of_date": as_of_date or now().split()[0],
			"last_entry": last_entry[0].name,
			"last_entry_datetime": str(last_entry[0].posting_datetime)
		}
	else:
		return {
			"employee": employee,
			"balance": 0.0,
			"as_of_date": as_of_date or now().split()[0],
			"last_entry": None,
			"last_entry_datetime": None
		}


@frappe.whitelist()
def get_overtime_ledger_entries(employee, from_date=None, to_date=None, limit=100):
	"""
	Get overtime ledger entries for an employee with filters
	
	Args:
		employee: Employee ID
		from_date: Optional start date
		to_date: Optional end date
		limit: Maximum number of entries to return (default 100)
	
	Returns:
		list: List of overtime ledger entries with running balance
	"""
	# Use Query Builder
	OLE = frappe.qb.DocType("Overtime Ledger Entry")
	
	query = (
		frappe.qb.from_(OLE)
		.select(
			OLE.name,
			OLE.posting_date,
			OLE.posting_time,
			OLE.posting_datetime,
			OLE.voucher_type,
			OLE.voucher_no,
			OLE.hour_variance,
			OLE.balance_before,
			OLE.balance_after,
			OLE.target_hours,
			OLE.actual_hours,
			OLE.remarks,
			OLE.is_cancelled
		)
		.where(OLE.employee == employee)
		.where(OLE.is_cancelled == 0)
	)
	
	# Add optional filters
	if from_date:
		query = query.where(OLE.posting_date >= from_date)
	
	if to_date:
		query = query.where(OLE.posting_date <= to_date)
	
	# Add ordering and limit
	query = (
		query
		.orderby(OLE.posting_datetime, order=Order.desc)
		.orderby(OLE.creation, order=Order.desc)
		.limit(limit)
	)
	
	entries = query.run(as_dict=True)
	
	return entries


@frappe.whitelist()
def repost_overtime_for_employee(employee, from_date):
	"""
	Manually trigger reposting of overtime balances for an employee
	Useful for corrections or data fixes
	
	Args:
		employee: Employee ID
		from_date: Date to start reposting from (format: YYYY-MM-DD)
	
	Returns:
		dict: Status message
	"""
	try:
		update_entries_after(employee, from_date, "00:00:00")
		
		# Get updated balance
		balance_info = get_employee_overtime_balance(employee)
		
		frappe.msgprint(
			_("Successfully reposted overtime entries for {0}. Current balance: {1} hours").format(
				employee, balance_info.get("balance")
			),
			alert=True,
			indicator="green"
		)
		
		return {
			"status": "success",
			"message": "Reposting completed successfully",
			"current_balance": balance_info.get("balance")
		}
	except Exception as e:
		frappe.throw(_("Error reposting overtime entries: {0}").format(str(e)))