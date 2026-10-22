"""Projects live in folders: <root>/<slug>/project.json plus songs/, shows/, shaders/."""

import os
import re
import tempfile
from pathlib import Path

from lsg.model.project import Project

PROJECT_FILE = "project.json"
SUBDIRS = ("songs", "shows", "shaders")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class ProjectStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def project_dir(self, slug: str) -> Path:
        return self.root / slug

    def list(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / PROJECT_FILE).is_file())

    def create(self, project: Project) -> str:
        base = slugify(project.name)
        slug, n = base, 2
        while self.project_dir(slug).exists():
            slug, n = f"{base}-{n}", n + 1
        for sub in SUBDIRS:
            (self.project_dir(slug) / sub).mkdir(parents=True)
        self.save(slug, project)
        return slug

    def load(self, slug: str) -> Project:
        text = (self.project_dir(slug) / PROJECT_FILE).read_text(encoding="utf-8")
        return Project.model_validate_json(text)

    def save(self, slug: str, project: Project) -> None:
        atomic_write_text(self.project_dir(slug) / PROJECT_FILE, project.model_dump_json(indent=2))
