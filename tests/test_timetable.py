import json
import random
import unittest

from timetable_solver import core, create_app
from timetable_solver.core import EXAMPLE, Infeasible, Lesson, Problem, construct, expand, improve, load, quick_checks, soft_cost, solve, view, violations


def planted(seed, days=5, periods=6, classes=4, fill=0.85):
    """A random instance built from a hidden valid timetable, so a solution is known to exist."""
    rng = random.Random(seed)
    teachers = [f"T{i}" for i in range(classes + 2)]
    rooms = {f"R{i}": "class" for i in range(classes)}
    lessons = []
    busy = set()
    for c in range(classes):
        for d in range(days):
            for p in range(periods):
                if rng.random() < fill:
                    t = rng.choice(teachers)
                    if (t, d, p) not in busy:
                        busy.add((t, d, p))
                        lessons.append(Lesson(len(lessons), f"C{c}", f"S{rng.randint(0, 5)}", t))
    return Problem(days, periods, lessons, rooms)


class TestHardRules(unittest.TestCase):
    def test_example_solves_cleanly(self):
        p = load(EXAMPLE)
        plan, _ = solve(p, 1, 3000)
        self.assertEqual(violations(p, plan), [])

    def test_random_full_instances(self):
        for seed in range(12):
            p = planted(seed)
            self.assertEqual(violations(p, construct(p, seed)), [])

    def test_blocked_times_are_respected(self):
        p = load(EXAMPLE)
        plan = construct(p, 2)
        for l in p.lessons:
            if l.teacher == "Mr Rahman":
                self.assertNotIn(plan[l.id][0], p.blocked["Mr Rahman"])

    def test_lab_lessons_get_a_lab(self):
        p = load(EXAMPLE)
        plan = construct(p, 3)
        for l in p.lessons:
            if l.subject == "ICT":
                self.assertEqual(plan[l.id][1], "Lab")

    def test_checker_finds_each_problem(self):
        ls = [Lesson(0, "A", "x", "T"), Lesson(1, "B", "y", "T")]
        p = Problem(2, 2, ls, {"R": "class", "L": "lab"}, {"A": {(1, 1)}})
        self.assertTrue(any("teacher T is double-booked" in v for v in violations(p, {0: ((0, 0), "R"), 1: ((0, 0), "L")})))
        self.assertTrue(any("needs a class room" in v for v in violations(p, {0: ((0, 0), "L"), 1: ((0, 1), "R")})))
        self.assertTrue(any("unavailable" in v for v in violations(p, {0: ((1, 1), "R"), 1: ((0, 1), "R")})))
        self.assertTrue(any("not placed" in v for v in violations(p, {0: ((0, 0), "R")})))
        self.assertTrue(any("outside the week" in v for v in violations(p, {0: ((9, 0), "R"), 1: ((0, 1), "R")})))


class TestImpossible(unittest.TestCase):
    def test_too_many_lessons_for_a_teacher(self):
        p = Problem(1, 2, expand([{"klass": "A", "subject": "x", "teacher": "T", "per_week": 1}, {"klass": "B", "subject": "x", "teacher": "T", "per_week": 2}]), {"R": "class", "R2": "class"})
        with self.assertRaises(Infeasible) as c:
            construct(p)
        self.assertIn("teacher T has 3 lessons", str(c.exception))

    def test_missing_room_type(self):
        p = Problem(1, 2, expand([{"klass": "A", "subject": "x", "teacher": "T", "per_week": 1, "room_type": "lab"}]), {"R": "class"})
        self.assertIn("no room of type lab", quick_checks(p)[0])

    def test_blocked_counts_against_capacity(self):
        p = Problem(1, 3, expand([{"klass": "A", "subject": "x", "teacher": "T", "per_week": 3}]), {"R": "class"}, {"T": {(0, 0)}})
        with self.assertRaises(Infeasible):
            construct(p)

    def test_search_proves_a_subtle_impossibility(self):
        """Each count looks fine, yet T1 and T2 both need the single free period of class B."""
        reqs = [{"klass": "A", "subject": "x", "teacher": "T1", "per_week": 1}, {"klass": "B", "subject": "y", "teacher": "T1", "per_week": 1}, {"klass": "C", "subject": "z", "teacher": "T1", "per_week": 1}]
        p = Problem(1, 2, expand(reqs), {"R1": "class", "R2": "class", "R3": "class"})
        with self.assertRaises(Infeasible):
            construct(p)
        reqs = [{"klass": "A", "subject": "x", "teacher": "T1", "per_week": 1}, {"klass": "A", "subject": "y", "teacher": "T2", "per_week": 1}, {"klass": "B", "subject": "x", "teacher": "T1", "per_week": 1}, {"klass": "B", "subject": "y", "teacher": "T2", "per_week": 1}, {"klass": "C", "subject": "y", "teacher": "T2", "per_week": 1}]
        p = Problem(1, 2, expand(reqs), {"R1": "class", "R2": "class", "R3": "class"})
        with self.assertRaises(Infeasible):
            construct(p)


class TestSoftGoals(unittest.TestCase):
    def test_cost_examples(self):
        ls = [Lesson(0, "A", "x", "T"), Lesson(1, "A", "x", "T")]
        p = Problem(2, 4, ls, {"R": "class"})
        self.assertGreater(soft_cost(p, {0: ((0, 0), "R"), 1: ((0, 1), "R")}), soft_cost(p, {0: ((0, 0), "R"), 1: ((1, 0), "R")}))
        gap = soft_cost(p, {0: ((0, 0), "R"), 1: ((0, 3), "R")}, {"repeat": 0, "uneven": 0})
        self.assertEqual(gap, 6)

    def test_annealing_improves_and_stays_valid(self):
        p = load(EXAMPLE)
        start = construct(p, 4)
        plan, cost = improve(p, start, 8000, 4)
        self.assertEqual(violations(p, plan), [])
        self.assertLess(cost, soft_cost(p, start) * 0.8)
        self.assertEqual(cost, soft_cost(p, plan))

    def test_same_seed_same_timetable(self):
        p = load(EXAMPLE)
        self.assertEqual(solve(p, 7, 500), solve(p, 7, 500))


class TestViews(unittest.TestCase):
    def test_every_lesson_shows_in_class_and_teacher_views(self):
        p = load(EXAMPLE)
        plan = construct(p, 5)
        for key in ("klass", "teacher"):
            n = sum(1 for v in {getattr(l, key) for l in p.lessons} for row in view(p, plan, key, v) for cell in row if cell)
            self.assertEqual(n, len(p.lessons))

    def test_expand(self):
        self.assertEqual(len(expand([{"klass": "A", "subject": "x", "teacher": "T", "per_week": 3}])), 3)


class TestApp(unittest.TestCase):
    def setUp(self):
        self.a = create_app(":memory:")

    def test_flow(self):
        self.assertIn("Solve", self.a.get("/").body.decode())
        r = self.a.post("/", input=json.dumps(EXAMPLE), seed=1, steps=500)
        self.assertEqual(r.status, 303)
        url = r.headers["Location"]
        self.assertIn("Comfort penalty", self.a.get(url).body.decode())
        page = self.a.get(url + "/klass/6A").body.decode()
        self.assertIn("Bangla", page)
        self.assertEqual(self.a.get(url + "/teacher/Mr%20Hasan").status, 200)
        self.assertIn("Mr Hasan", self.a.get(url + "/teacher/Mr%20Hasan").body.decode())
        self.assertEqual(self.a.get(url + "/bad/x").status, 404)

    def test_bad_json(self):
        self.assertEqual(self.a.post("/", input="{not json", seed=1).status, 400)

    def test_impossible_is_explained(self):
        data = dict(days=1, periods=1, rooms={"R": "class"}, requirements=[{"klass": "A", "subject": "x", "teacher": "T", "per_week": 2}])
        r = self.a.post("/", input=json.dumps(data), seed=1)
        self.assertEqual(r.status, 400)
        self.assertIn("only 1 free", r.body.decode())


if __name__ == "__main__":
    unittest.main()
