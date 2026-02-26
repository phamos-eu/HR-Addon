from setuptools import setup, find_packages

# get version from __version__ variable in hr_addon/__init__.py
from hr_addon import __version__ as version

setup(
    name="hr_addon",
    version=version,
    description="Addon for Erpnext attendance and employee checkins",
    author="Phamos GmbH",
    author_email="support@phamos.eu",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=["icalendar"]
)
