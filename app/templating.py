from pathlib import Path

from fastapi.templating import Jinja2Templates

_template_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))
