import re
from pathlib import Path

from setuptools import find_packages, setup

with open("requirements.txt") as f:
	install_requires = [
		line.strip()
		for line in f.read().splitlines()
		if line.strip() and not line.strip().startswith("#")
	]

version_file = Path("hr_addon/__init__.py").read_text()
version = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", version_file, re.M).group(1)

setup(
	name="hr_addon",
	version=version,
	description="Addon for Erpnext attendance and employee checkins",
	author="phamos.eu",
	author_email="support@phamos.eu",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires,
)
