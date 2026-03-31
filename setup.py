from setuptools import setup, find_packages

setup(
	name="hr_addon",
	version="0.1.0",
	description="Addon for Erpnext attendance and employee checkins",
	author="Phamos GmbH",
	author_email="support@phamos.eu",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=["icalendar"],
)