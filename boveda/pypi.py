#!/usr/bin/python3

import requests

def get_pypi_package_info(package_name: str) -> dict:
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            return {}

        return r.json()

    except Exception:
        return {}



class PyPIPackage:
    def __init__(self, package_name: str):
        self.package_name = package_name
        self.data = get_pypi_package_info(package_name)

        self.info = self.data.get("info", {}) if self.data else {}
        self.project_urls = self.info.get("project_urls", {}) or {}

    def name(self):
        return self.info.get("name")

    def version(self):
        return self.info.get("version")

    def summary(self):
        return self.info.get("summary")

    def description(self):
        return self.info.get("description")

    def author(self):
        return self.info.get("author")

    def author_email(self):
        return self.info.get("author_email")

    def license(self):
        return self.info.get("license")

    def home_page(self):
        return self.info.get("home_page")

    def requires_python(self):
        return self.info.get("requires_python")

    def dependencies(self):
        return self.info.get("requires_dist")

    # --- project_urls extras ---

    def project_urls(self):
        return self.project_urls

    def source_url(self):
        # PyPI convention: chave pode ser "Source" ou variações
        return (
            self.project_urls.get("Source")
            or self.project_urls.get("Source Code")
            or self.project_urls.get("Repository")
        )

    def documentation_url(self):
        return self.project_urls.get("Documentation")

    def bug_tracker_url(self):
        return self.project_urls.get("Bug Tracker")



