import os
import subprocess

def ensure_mime_type(ext, mime_type, comment=None):
    """
    Garante que um MIME customizado existe no sistema.

    :param ext: extensão sem ponto (ex: "npy")
    :param mime_type: ex: "application/x-npy"
    :param comment: descrição opcional
    :return: True se criou, False se já existia
    """

    mime_dir = os.path.expanduser("~/.local/share/mime/packages")
    mime_file = os.path.join(mime_dir, f"{ext}.xml")

    if comment is None:
        comment = f"{ext.upper()} file"

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
    <mime-type type="{mime_type}">
        <comment>{comment}</comment>
        <glob pattern="*.{ext}"/>
    </mime-type>
</mime-info>
"""

    # Criar diretório se necessário
    os.makedirs(mime_dir, exist_ok=True)

    # Criar apenas se não existir
    if not os.path.exists(mime_file):
        with open(mime_file, "w", encoding="utf-8") as f:
            f.write(xml_content)

        # Atualizar banco MIME
        try:
            subprocess.run(
                ["update-mime-database", os.path.expanduser("~/.local/share/mime")],
                check=True
            )
        except Exception as e:
            print("Erro ao atualizar MIME database:", e)

        return True

    return False
