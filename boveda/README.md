Quero fazer um program em pyton e pyqt5 que deriva de QMainWindow

Quero fazer um program que ao iniciar lee todos os arquivos JSOn desde REPOSITORIES_PATH,
A partir de ali mostra  numa lista de iconos e nomes com todos os packages nos json, 
se possivel pode agregar um simbollo para indicar que ja esta instalado 
(pode ser background de outra cor, ou um simbolo de check sobreposto no icone, ou algum outro jeito, quero algo bonito e elegante vc escolhe o jeito),
Esse é o unico trabalho que deve ser feito automatico ao inicio, prefiro que faça essa leitura mediante uma progress bar e usando threads.
os iconos sao mostrados agrupados por categorias, que podem ser collapsadas ou expandidas para facilitar a leitura.
Acima de todo tambem tem um buscador, que procura um texto por nome ou por categoria.
Ao fazer click num icono se passa a um janela de descriçao do pacote, 
ali se descarga e se mostra os metadatos do package, nesta ordem
* titulo do package e icono
* Summary do pacakge
* Version
* Uma ruleta com os screenshots
* Author
* email
* Licença
* homepage 
* project_urls
* installed+version: (or not installed se nao instalado - Todo en negrito)
Acima de todos esses dados um botao de install/uninstall outro para update
A installaçao usa pipx


O formato de ingresso de datos é desde o filepath REPOSITORIES_PATH, 
o program busca jsons assim

```
for file in repository_path.glob("*.json"):
    load_repository(file)
```


cada repository tem o formato json

```
{
    "name": "Official",
    "author": "TrucomanX",
    "packages": [
        {
            "name": "httpie"
        },
        {
            "name": "search_file_content",
            "icon": "https://.../filename.png",
            "screenshots": [ "https://.../filename.png" ],
            "categories": [ "Utilities", ... ],
            "enabled": true
        }
    ]
}
```
Dentro de "packages" so "name" é obrigatorio. o resto os valores por falta sao.
```
    "icon": "",
    "screenshots": [],
    "categories": ["Any"],
    "enabled": true
```


A ideia é instalar os pacotes usando pipx.
```
subprocess.run(["pipx", "install", package_name], check=True)
add_installed_package(package_name)
```


# Arquivos propostos

## File: `modules/pypi.py`

```python
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

```

## File: `modules/installed.py`

```python
#!/usr/bin/python3

import json
from pathlib import Path
from importlib.metadata import distribution



def get_executables(package_name: str) -> list[str]:
    try:
        dist = distribution(package_name)

        return sorted(
            ep.name
            for ep in dist.entry_points
            if ep.group == "console_scripts"
        )

    except Exception:
        return []


def add_installed_package(installed_filepath: str, package_name: str):
    FilePath = Path(installed_filepath)
    
    if FilePath.exists():
        data = json.loads(FilePath.read_text())
    else:
        data = {}

    data[package_name] = {
        "executables": get_executables(package_name)
    }

    FilePath.write_text(json.dumps(data, indent=4))

```

## File: `installed.json`

```
{
    "httpie": {
        "version": "3.2.4",
        "executables": [
            "http",
            "httpie",
            "https"
        ]
    },
    "black": {
        "version": "3.2.1",
        "executables": [
            "black",
            "blackd"
        ]
    }
}

```



