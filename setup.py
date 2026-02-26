from setuptools import setup, find_packages
import re
from pathlib import Path

# get version from __version__ variable in hr_addon/__init__.py
def get_version():
    init_py = Path("hr_addon/__init__.py")
    if init_py.exists():
        content = init_py.read_text()
        match = re.search(r"^__version__\s*=\s*['\"]([^'\"]*)['\"]", content, re.M)
        if match:
            return match.group(1)
    return "0.1.0"

setup(
    name="hr_addon",
    version=get_version(),
    description="Addon for Erpnext attendance and employee checkins",
    author="Phamos GmbH",
    author_email="support@phamos.eu",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=["icalendar"]
)
