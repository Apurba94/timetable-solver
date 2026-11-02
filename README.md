# Timetable Solver

Making a school timetable by hand takes days and rarely ends well. This tool finds one with no clashes, then improves it, and it tells you plainly when no timetable can exist. It runs offline.

```
python -m timetable_solver
```

Then open http://127.0.0.1:8023. The page comes with a worked example to edit. Python 3.10 or newer is all it needs.

```python
from timetable_solver import core

problem = core.load(core.EXAMPLE)
plan, penalty = core.solve(problem, seed=1)
print(core.violations(problem, plan))              # []
print(core.view(problem, plan, "klass", "6A"))
```

## What it handles

**Hard rules, which are never broken:** no teacher, class or room in two places at once, each lesson in the right type of room, such as a computer lab, and teachers or classes who are unavailable at certain times.

**Soft goals, which it tries to meet:** a subject not twice in one day for a class, no gaps in a class's day, teachers' lessons spread evenly across the week, and no more than three lessons in a row for a teacher.

## How it works

1. **Quick checks** catch impossible inputs early and explain them, for example: "teacher Mr Khan has 31 lessons but only 28 free periods".
2. **Constraint search** places the hardest lesson first, with backtracking and forward checking.
3. **Simulated annealing** then moves and swaps lessons to improve the soft goals. Every move keeps the hard rules true, so the timetable stays valid throughout.

Each result is verified by `violations`, an independent check that shares no code with the solver's bookkeeping.

## How it is tested

Random schools are built from a hidden valid timetable, so a solution is known to exist, and the solver must find one. Small impossible cases must be proven impossible, including ones where the simple counts look fine. Annealing must cut the penalty by at least 20% while staying valid.

## Limits

Tested on schools with a few classes and about 150 lessons. Large, nearly full schools may need another seed, or hit the search limit. Double periods are in the data model but are not scheduled yet. The input is JSON, which suits a technical person more than a busy head teacher.

MIT licence.
