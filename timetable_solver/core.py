"""School timetabling: find a timetable with no clashes, then make it pleasant.

Stage one treats the problem as constraint satisfaction: place the hardest lessons first, with
backtracking. Stage two uses simulated annealing to improve soft goals while keeping every hard rule.
"""
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Lesson:
    id: int
    klass: str
    subject: str
    teacher: str
    room_type: str = "class"
    double: bool = False


@dataclass
class Problem:
    days: int
    periods: int
    lessons: list
    rooms: dict                         # {room: type}
    blocked: dict = field(default_factory=dict)      # {teacher or class: set of (day, period)}

    def slots(self):
        return [(d, p) for d in range(self.days) for p in range(self.periods)]


class Infeasible(Exception):
    pass


def expand(requirements):
    """requirements: list of dicts with klass, subject, teacher, per_week and optional room_type. Returns lessons."""
    out = []
    for r in requirements:
        for _ in range(r["per_week"]):
            out.append(Lesson(len(out), r["klass"], r["subject"], r["teacher"], r.get("room_type", "class")))
    return out


def quick_checks(problem):
    """Reasons a timetable cannot exist, found before any search, in words a person can act on."""
    reasons = []
    total = len(problem.slots())
    for key, name in (("klass", "class"), ("teacher", "teacher")):
        load = defaultdict(int)
        for l in problem.lessons:
            load[getattr(l, key)] += 1
        for who, n in load.items():
            free = total - len(problem.blocked.get(who, ()))
            if n > free:
                reasons.append(f"{name} {who} has {n} lessons but only {free} free periods")
    types = defaultdict(int)
    for l in problem.lessons:
        types[l.room_type] += 1
    for kind, n in types.items():
        rooms = sum(1 for t in problem.rooms.values() if t == kind)
        if rooms == 0:
            reasons.append(f"no room of type {kind}")
        elif n > rooms * total:
            reasons.append(f"{n} {kind} lessons, but {rooms} rooms give only {rooms * total} places")
    return reasons


class Grid:
    """Who is busy when, with fast add and remove."""

    def __init__(self, problem):
        self.p = problem
        self.teacher = {}
        self.klass = {}
        self.room = {}
        self.at = {}

    def can(self, l, slot, room):
        return (l.teacher, slot) not in self.teacher and (l.klass, slot) not in self.klass and (room, slot) not in self.room and slot not in self.p.blocked.get(l.teacher, ()) and slot not in self.p.blocked.get(l.klass, ()) and self.p.rooms[room] == l.room_type

    def put(self, l, slot, room):
        self.teacher[(l.teacher, slot)] = l.id
        self.klass[(l.klass, slot)] = l.id
        self.room[(room, slot)] = l.id
        self.at[l.id] = (slot, room)

    def take(self, l):
        slot, room = self.at.pop(l.id)
        del self.teacher[(l.teacher, slot)]
        del self.klass[(l.klass, slot)]
        del self.room[(room, slot)]
        return slot, room


def construct(problem, seed=0, limit=2_000_000):
    """Backtracking with most-constrained-first and forward checking."""
    for_reasons = quick_checks(problem)
    if for_reasons:
        raise Infeasible("; ".join(for_reasons))
    rng = random.Random(seed)
    grid = Grid(problem)
    rooms_by_type = defaultdict(list)
    for r, t in problem.rooms.items():
        rooms_by_type[t].append(r)
    slots = problem.slots()
    rng.shuffle(slots)
    steps = [0]
    by_id = {l.id: l for l in problem.lessons}

    def options(l):
        out = []
        for s in slots:
            for r in rooms_by_type[l.room_type]:
                if grid.can(l, s, r):
                    out.append((s, r))
                    break
        return out

    def solve(todo):
        if not todo:
            return True
        steps[0] += 1
        if steps[0] > limit:
            raise Infeasible("search limit reached without a solution: try fewer constraints or another seed")
        best, best_opts = None, None
        for lid in todo:
            o = options(by_id[lid])
            if not o:
                return False                     # forward check: this lesson can never be placed now
            if best is None or len(o) < len(best_opts):
                best, best_opts = lid, o
                if len(o) == 1:
                    break
        l = by_id[best]
        rest = todo - {best}
        for s, r in best_opts:
            grid.put(l, s, r)
            if solve(rest):
                return True
            grid.take(l)
        return False
    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), len(problem.lessons) + 200))
    if not solve(frozenset(l.id for l in problem.lessons)):
        raise Infeasible("the constraints cannot all be met")
    return dict(grid.at)


def violations(problem, plan):
    """An independent check of the hard rules, separate from the solver's own bookkeeping."""
    out = []
    seen = defaultdict(list)
    for l in problem.lessons:
        if l.id not in plan:
            out.append(f"lesson {l.id} is not placed")
            continue
        slot, room = plan[l.id]
        if not (0 <= slot[0] < problem.days and 0 <= slot[1] < problem.periods):
            out.append(f"lesson {l.id} is outside the week")
        if problem.rooms.get(room) != l.room_type:
            out.append(f"lesson {l.id} needs a {l.room_type} room")
        for who in (l.teacher, l.klass):
            if slot in problem.blocked.get(who, ()):
                out.append(f"{who} is unavailable at {slot}")
        for tag, who in (("teacher", l.teacher), ("class", l.klass), ("room", room)):
            seen[(tag, who, slot)].append(l.id)
    for (tag, who, slot), ids in seen.items():
        if len(ids) > 1:
            out.append(f"{tag} {who} is double-booked at {slot}")
    return out


def soft_cost(problem, plan, weights=None):
    """Lower is better. Penalties: a subject twice in one day, gaps in a class's day, a heavy day
    for a teacher, and more than three lessons in a row for a teacher."""
    w = {"repeat": 5, "gap": 3, "uneven": 1, "run": 2, **(weights or {})}
    by_class = defaultdict(lambda: defaultdict(list))
    by_teacher = defaultdict(lambda: defaultdict(list))
    repeat = defaultdict(int)
    for l in problem.lessons:
        (d, p), _ = plan[l.id]
        by_class[l.klass][d].append(p)
        by_teacher[l.teacher][d].append(p)
        repeat[(l.klass, l.subject, d)] += 1
    cost = sum(w["repeat"] * (n - 1) for n in repeat.values() if n > 1)
    for days in by_class.values():
        for ps in days.values():
            ps.sort()
            cost += w["gap"] * (ps[-1] - ps[0] + 1 - len(ps))
    for days in by_teacher.values():
        loads = [len(days.get(d, ())) for d in range(problem.days)]
        cost += w["uneven"] * (max(loads) - min(loads))
        for ps in days.values():
            ps.sort()
            run = 1
            for a, b in zip(ps, ps[1:]):
                run = run + 1 if b == a + 1 else 1
                if run > 3:
                    cost += w["run"]
    return cost


def improve(problem, plan, steps=20000, seed=0, start_temp=4.0, weights=None):
    """Simulated annealing. Moves keep every hard rule true, so the plan stays valid at every step."""
    rng = random.Random(seed)
    grid = Grid(problem)
    by_id = {l.id: l for l in problem.lessons}
    for lid, (slot, room) in plan.items():
        grid.put(by_id[lid], slot, room)
    slots = problem.slots()
    rooms = list(problem.rooms)
    ids = list(plan)
    cost = soft_cost(problem, grid.at, weights)
    best, best_plan = cost, dict(grid.at)
    for i in range(steps):
        temp = start_temp * (1 - i / steps) + 1e-3
        a = by_id[rng.choice(ids)]
        s2, r2 = rng.choice(slots), rng.choice(rooms)
        s1, r1 = grid.at[a.id]
        other = grid.klass.get((a.klass, s2))
        moved = []
        grid.take(a)
        if other is not None and other != a.id:           # swap with the class's lesson at that time
            b = by_id[other]
            sb, rb = grid.take(b)
            if grid.can(a, s2, rb) and grid.can(b, s1, r1):
                grid.put(a, s2, rb)
                grid.put(b, s1, r1)
                moved = [(a, s1, r1), (b, sb, rb)]
            else:
                grid.put(b, sb, rb)
                grid.put(a, s1, r1)
                continue
        elif grid.can(a, s2, r2):
            grid.put(a, s2, r2)
            moved = [(a, s1, r1)]
        else:
            grid.put(a, s1, r1)
            continue
        new = soft_cost(problem, grid.at, weights)
        if new <= cost or rng.random() < math.exp((cost - new) / temp):
            cost = new
            if cost < best:
                best, best_plan = cost, dict(grid.at)
        else:
            for l, _, _ in moved:
                grid.take(l)
            for l, s, r in moved:
                grid.put(l, s, r)
    return best_plan, best


def solve(problem, seed=0, steps=20000, weights=None):
    plan = construct(problem, seed)
    return improve(problem, plan, steps, seed, weights=weights)


def view(problem, plan, key, value):
    """A timetable for one class, teacher or room. key: klass, teacher or room."""
    grid = [["" for _ in range(problem.days)] for _ in range(problem.periods)]
    for l in problem.lessons:
        (d, p), room = plan[l.id]
        if (key == "room" and room == value) or (key != "room" and getattr(l, key) == value):
            detail = {"klass": f"{l.subject} ({l.teacher}, {room})", "teacher": f"{l.klass} {l.subject} ({room})", "room": f"{l.klass} {l.subject} ({l.teacher})"}[key]
            grid[p][d] = detail
    return grid


def load(data):
    """Build a problem from a plain dict, as read from JSON."""
    blocked = {k: {tuple(s) for s in v} for k, v in data.get("blocked", {}).items()}
    return Problem(data["days"], data["periods"], expand(data["requirements"]), data["rooms"], blocked)


EXAMPLE = {"days": 5, "periods": 6, "rooms": {"R1": "class", "R2": "class", "R3": "class", "Lab": "lab"},
           "blocked": {"Mr Rahman": [[0, 0], [0, 1], [4, 5]]},
           "requirements": [{"klass": c, "subject": s, "teacher": t, "per_week": n, **({"room_type": "lab"} if s == "ICT" else {})}
                            for c, (a, b) in {"6A": ("Ms Akter", "Mr Rahman"), "7A": ("Ms Akter", "Ms Khan"), "8A": ("Mr Islam", "Ms Khan")}.items()
                            for s, t, n in (("Bangla", a, 5), ("English", b, 5), ("Maths", "Mr Hasan", 5), ("Science", "Ms Sultana", 4), ("ICT", "Mr Roy", 2))]}


def to_json(problem, plan):
    return json.dumps([{"class": l.klass, "subject": l.subject, "teacher": l.teacher, "day": plan[l.id][0][0], "period": plan[l.id][0][1], "room": plan[l.id][1]} for l in problem.lessons], ensure_ascii=False, indent=1)
