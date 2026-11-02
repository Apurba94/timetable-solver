"""Start the app: python -m timetable_solver [data.db] [--port 8023]"""
import sys

from .fieldkit import main_cli
from .web import create_app

sys.exit(main_cli(create_app, "timetable.db", 8023, sys.argv))
