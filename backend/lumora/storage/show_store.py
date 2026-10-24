"""Shows (<project>/shows/<id>.json) and shaders (<project>/shaders/<name>.py)."""

import json
import re
import shutil
import time
from pathlib import Path

from lumora.model.show import Show
from lumora.render.shaders import NAME_RE, Shader, ShaderError
from lumora.storage.history import History, show_summary
from lumora.storage.project_store import atomic_write_text

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ShowStore:
    def __init__(self, project_dir: Path):
        self.shows_dir = project_dir / "shows"
        self.shaders_dir = project_dir / "shaders"

    # shows
    def _show_path(self, show_id: str) -> Path:
        if not _ID_RE.match(show_id) or show_id == "order":  # order.json holds the list order
            raise KeyError(show_id)
        return self.shows_dir / f"{show_id}.json"

    def list(self) -> list[Show]:
        """Shows in the user's order (order.json); shows not in it follow by name."""
        if not self.shows_dir.exists():
            return []
        shows = [
            Show.model_validate_json(p.read_text(encoding="utf-8"))
            for p in self.shows_dir.glob("*.json")
            if p.name != "order.json"
        ]
        rank = {sid: i for i, sid in enumerate(self.order())}
        return sorted(shows, key=lambda s: (rank.get(s.id, len(rank)), s.name.lower()))

    def _order_path(self) -> Path:
        return self.shows_dir / "order.json"

    def order(self) -> list[str]:
        path = self._order_path()
        if not path.is_file():
            return []
        try:
            return [str(x) for x in json.loads(path.read_text(encoding="utf-8"))]
        except (ValueError, TypeError):
            return []

    def set_order(self, ids: list[str]) -> None:
        known = {s.id for s in self.list()}
        ordered = [i for i in dict.fromkeys(ids) if i in known]
        self.shows_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._order_path(), json.dumps(ordered))

    def get(self, show_id: str) -> Show:
        path = self._show_path(show_id)
        if not path.is_file():
            raise KeyError(show_id)
        return Show.model_validate_json(path.read_text(encoding="utf-8"))

    def history(self, show_id: str) -> History:
        self._show_path(show_id)  # validates the id
        return History(self.shows_dir / f"{show_id}.history")

    def save(self, show: Show, source: str = "ui") -> str:
        """Write the show and record a version; returns the version id."""
        is_new = not self._show_path(show.id).is_file()
        if show.created is None:  # keep the date of an existing show (edits may not send it)
            show.created = self.created(self.get(show.id)) if not is_new else round(time.time(), 3)
        content = show.model_dump_json(indent=2)
        history = self.history(show.id)
        previous = history.latest_content()
        summary = show_summary(json.loads(previous) if previous else None, json.loads(content))
        atomic_write_text(self._show_path(show.id), content)
        if is_new and self._order_path().is_file():  # new shows go to the end of a custom order
            atomic_write_text(self._order_path(), json.dumps([*self.order(), show.id]))
        return history.record(content, source, summary)

    def created(self, show: Show) -> float | None:
        """When the show was created: stored with it, else its oldest version, else the file date."""
        if show.created is not None:
            return show.created
        first = self.history(show.id).first_time()
        if first is not None:
            return round(first, 3)
        path = self._show_path(show.id)
        return round(path.stat().st_mtime, 3) if path.is_file() else None

    def restore(self, show_id: str, version_id: str) -> Show:
        show = Show.model_validate_json(self.history(show_id).get(version_id))
        self.save(show, "restore")
        return show

    def delete(self, show_id: str) -> None:
        path = self._show_path(show_id)
        if not path.is_file():
            raise KeyError(show_id)
        path.unlink()
        shutil.rmtree(self.shows_dir / f"{show_id}.history", ignore_errors=True)
        if self._order_path().is_file():
            atomic_write_text(self._order_path(), json.dumps([i for i in self.order() if i != show_id]))

    # looks (custom ones; built-in looks live in lumora.render.looks)
    def _looks_path(self) -> Path:
        return self.shows_dir.parent / "looks.json"

    def looks(self) -> list:
        from lumora.render.looks import Look

        path = self._looks_path()
        if not path.is_file():
            return []
        return [Look.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]

    def save_look(self, look) -> None:
        looks = [x for x in self.looks() if x.id != look.id] + [look]
        atomic_write_text(self._looks_path(), json.dumps([x.model_dump() for x in looks], indent=2))

    def delete_look(self, look_id: str) -> None:
        looks = self.looks()
        if not any(x.id == look_id for x in looks):
            raise KeyError(look_id)
        atomic_write_text(self._looks_path(), json.dumps([x.model_dump() for x in looks if x.id != look_id], indent=2))

    # shaders
    def _shader_path(self, name: str) -> Path:
        if not NAME_RE.match(name):
            raise KeyError(name)
        return self.shaders_dir / f"{name}.py"

    def shader_names(self) -> list[str]:
        if not self.shaders_dir.exists():
            return []
        return sorted(p.stem for p in self.shaders_dir.glob("*.py") if NAME_RE.match(p.stem))

    def shader_source(self, name: str) -> str:
        path = self._shader_path(name)
        if not path.is_file():
            raise KeyError(name)
        return path.read_text(encoding="utf-8")

    def save_shader(self, name: str, source: str) -> Shader:
        shader = Shader(name, source)  # validates before writing
        atomic_write_text(self._shader_path(name), source)
        return shader

    def delete_shader(self, name: str) -> None:
        path = self._shader_path(name)
        if not path.is_file():
            raise KeyError(name)
        path.unlink()

    def load_shaders(self) -> tuple[dict[str, Shader], dict[str, str]]:
        """All loadable shaders plus load errors by name."""
        from lumora.render import shader_host

        shaders, errors = {}, {}
        for name in self.shader_names():
            try:
                shader = Shader(name, self.shader_source(name))
                shaders[name] = shader_host.IsolatedShader(shader) if shader_host.ENABLED else shader
            except ShaderError as exc:
                errors[name] = str(exc)
        return shaders, errors
