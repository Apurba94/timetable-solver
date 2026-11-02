"""The offline web app: paste a school's needs as JSON, then read and print the timetables."""
import json

from . import core
from .fieldkit import App, Fail, Raw, card, form, h, link, redirect, stats, table

SCHEMA = "CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, input TEXT NOT NULL, plan TEXT NOT NULL, cost REAL NOT NULL);"
DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def create_app(db="timetable.db"):
    a = App("Timetable Solver", db, SCHEMA, [("Solve", "/"), ("History", "/runs")])

    def load(run):
        r = a.row("SELECT * FROM runs WHERE id = ?", run)
        if r is None:
            raise Fail("No such timetable", 404)
        problem = core.load(json.loads(r["input"]))
        plan = {int(k): ((v[0][0], v[0][1]), v[1]) for k, v in json.loads(r["plan"]).items()}
        return r, problem, plan

    @a.route("/", ("GET", "POST"))
    def home(req):
        if req.method == "POST":
            text = req.text("input", limit=1_000_000)
            try:
                data = json.loads(text)
                problem = core.load(data)
                plan, cost = core.solve(problem, int(req.number("seed", 0)), int(req.number("steps", 5000, 0, 200000)))
            except (ValueError, KeyError, TypeError) as exc:
                raise Fail(f"Could not read that: {exc}") from None
            except core.Infeasible as exc:
                raise Fail(f"No timetable is possible: {exc}") from None
            problems = core.violations(problem, plan)
            if problems:
                raise Fail("Internal check failed: " + "; ".join(problems[:3]), 500)
            cur = a.run("INSERT INTO runs (input, plan, cost) VALUES (?, ?, ?)", text, json.dumps({k: [list(v[0]), v[1]] for k, v in plan.items()}), cost)
            return redirect(f"/run/{cur.lastrowid}")
        return a.page("Build a timetable", card("School requirements as JSON", form(a, "/", [("input", "Requirements", "textarea", json.dumps(core.EXAMPLE, indent=1)), ("seed", "Seed", "number", 1), ("steps", "Improvement steps", "number", 5000)], "Solve")))

    @a.route("/run/<id>")
    def run(req, id):
        r, problem, plan = load(id)
        classes = sorted({l.klass for l in problem.lessons})
        teachers = sorted({l.teacher for l in problem.lessons})
        links = " · ".join(f'<a href="/run/{id}/klass/{h(c)}">{h(c)}</a>' for c in classes)
        tlinks = " · ".join(f'<a href="/run/{id}/teacher/{h(t)}">{h(t)}</a>' for t in teachers)
        rlinks = " · ".join(f'<a href="/run/{id}/room/{h(x)}">{h(x)}</a>' for x in problem.rooms)
        return a.page("Timetable", stats([("Lessons", len(problem.lessons)), ("Comfort penalty", f"{r['cost']:g}"), ("Clashes", 0)]) + card("By class", links) + card("By teacher", tlinks) + card("By room", rlinks))

    @a.route("/run/<id>/<key>/<value>")
    def show(req, id, key, value):
        from urllib.parse import unquote
        if key not in ("klass", "teacher", "room"):
            raise Fail("No such view", 404)
        _, problem, plan = load(id)
        grid = core.view(problem, plan, key, unquote(value))
        rows = [{"p": i + 1, "cells": row} for i, row in enumerate(grid)]
        cols = [("Period", "p")] + [(DAYS[d % 7], (lambda d: lambda r: r["cells"][d])(d)) for d in range(problem.days)]
        return a.page(unquote(value), f'<div class="card">{table(rows, cols)}</div>')

    @a.route("/runs")
    def runs(req):
        return a.page("History", card("Timetables", table(a.rows("SELECT id, cost FROM runs ORDER BY id DESC"), [("Run", lambda r: link(f"/run/{r['id']}", r["id"])), ("Comfort penalty", "cost")])))

    return a
