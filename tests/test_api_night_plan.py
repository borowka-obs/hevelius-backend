"""
Tests for GET/POST /api/night-plan (OS-4, #46).

The night used throughout is 2026-01-15 at a Warsaw-like site: a long winter
night, so the sky geometry is comfortably unambiguous. Local sidereal time
around midnight is then roughly 7-8h, which is why the "visible" targets sit
near RA 7h and the deliberately-rejected ones don't.

Constraint rejections are made deterministic by using physically impossible
limits (a 180° minimum moon distance, a -90° maximum sun altitude) rather than
by depending on where the Moon actually is on that date.
"""

import datetime
import json
import os
import unittest

from flask_jwt_extended import create_access_token

from hevelius import db, night
from hevelius.api import app
from tests.dbtest import use_repository

NIGHT = "2026-01-15"

# Warsaw-ish site; the mount reaches from -40° to +90° declination.
SCOPE_LAT = 52.2
SCOPE_LON = 21.0
SCOPE_TZ = "Europe/Warsaw"

# Transits near local midnight on NIGHT, high above the horizon.
VISIBLE_RA_H = 7.0
VISIBLE_DEC = 40.0


class TestNightPlan(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        with app.app_context():
            token = create_access_token(
                identity=1, additional_claims={'permissions': 1, 'username': 'test_user'})
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        # Point the API at each test's throwaway DB, and always let go of it
        # again - even when the test fails part way through.
        self.addCleanup(os.environ.pop, 'HEVELIUS_DB_NAME', None)

    # --- fixtures -------------------------------------------------------

    def _db(self):
        """A connection that gets closed even if the test fails mid-fixture."""
        cnx = db.connect()
        self.addCleanup(cnx.close)
        return cnx

    def _ensure_task_states(self, cnx):
        """test-data-basic.psql carries states 0 and 1; planning also uses 3 and 6."""
        db.run_query(cnx, """INSERT INTO task_states (id, name, descr)
                             VALUES (3, 'IN QUEUE', 'in queue'), (6, 'DONE', 'done')
                             ON CONFLICT DO NOTHING""")

    def _prepare_scope(self, cnx, scope_id=1, lat=SCOPE_LAT, lon=SCOPE_LON,
                       min_dec=-40.0, max_dec=90.0, timezone=SCOPE_TZ):
        db.run_query(cnx, """UPDATE telescopes
                             SET lat = %s, lon = %s, alt = 100, min_dec = %s, max_dec = %s,
                                 timezone = %s
                             WHERE scope_id = %s""",
                     (lat, lon, min_dec, max_dec, timezone, scope_id))
        return scope_id

    def _insert_task(self, cnx, obj, ra=VISIBLE_RA_H, decl=VISIBLE_DEC, state=1, user_id=1,
                     scope_id=1, priority=0, min_alt=None, moon_distance=None,
                     max_moon_phase=None, max_sun_alt=None, skip_before=None, skip_after=None):
        return db.run_query(
            cnx,
            """INSERT INTO tasks (user_id, scope_id, object, ra, decl, exposure, state, priority,
                                  min_alt, moon_distance, max_moon_phase, max_sun_alt,
                                  skip_before, skip_after)
               VALUES (%s, %s, %s, %s, %s, 300, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING task_id""",
            (user_id, scope_id, obj, ra, decl, state, priority, min_alt, moon_distance,
             max_moon_phase, max_sun_alt,
             skip_before or '2000-01-01 00:00:00+00', skip_after or '3000-01-01 00:00:00+00'),
        )

    def _insert_filter(self, cnx, short_name, on_scope_id=1):
        filter_id = db.run_query(
            cnx, "INSERT INTO filters (short_name, full_name) VALUES (%s, %s) RETURNING filter_id",
            (short_name, f"{short_name} filter"))
        if on_scope_id is not None:
            db.run_query(cnx, "INSERT INTO telescope_filters (scope_id, filter_id) VALUES (%s, %s)",
                         (on_scope_id, filter_id))
        return filter_id

    def _insert_project(self, cnx, name, ra=VISIBLE_RA_H, decl=VISIBLE_DEC, scope_id=1,
                        active=True, priority=0, user_id=None, start_date=None, end_date=None):
        project_id = db.run_query(
            cnx,
            """INSERT INTO projects (name, description, scope_id, ra, decl, active, priority,
                                     start_date, end_date)
               VALUES (%s, '', %s, %s, %s, %s, %s, %s, %s) RETURNING project_id""",
            (name, scope_id, ra, decl, active, priority, start_date, end_date),
        )
        if user_id is not None:
            db.run_query(cnx, "INSERT INTO project_users (project_id, user_id) VALUES (%s, %s)",
                         (project_id, user_id))
        return project_id

    def _insert_subframe(self, cnx, project_id, filter_id, count=0, goal_count=10, active=True):
        return db.run_query(
            cnx,
            """INSERT INTO project_subframes (project_id, filter_id, exposure_time, count,
                                              goal_count, active)
               VALUES (%s, %s, 300, %s, %s, %s) RETURNING id""",
            (project_id, filter_id, count, goal_count, active),
        )

    # --- helpers --------------------------------------------------------

    def _plan(self, query, expect=200):
        response = self.app.get(f'/api/night-plan?{query}', headers=self.headers)
        self.assertEqual(response.status_code, expect, response.data)
        return json.loads(response.data)

    def _labels(self, plan, kind="task"):
        key = "object" if kind == "task" else "name"
        return [item[kind][key] for item in plan["items"] if item["kind"] == kind]

    def _item_labels(self, plan):
        """Every item's name, tasks and projects alike, in plan order."""
        return [item[item["kind"]].get("object") or item[item["kind"]].get("name")
                for item in plan["items"]]

    def _reasons(self, plan):
        return {entry["name"]: entry["reason"] for entry in plan["excluded"]}

    # --- the night itself -----------------------------------------------

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_describes_the_night(self, config):
        """The response frames the plan: night date, sunset/sunrise, moon."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}')

        self.assertEqual(plan['scope_id'], 1)
        self.assertEqual(plan['scope_name'], 'test-scope')
        self.assertEqual(plan['night_date'], NIGHT)
        self.assertEqual(plan['timezone'], SCOPE_TZ)
        # Mid-January in Warsaw: sunset mid-afternoon UTC, sunrise next morning.
        self.assertTrue(plan['night_start_utc'].startswith('2026-01-15T'), plan['night_start_utc'])
        self.assertTrue(plan['night_end_utc'].startswith('2026-01-16T'), plan['night_end_utc'])
        self.assertLess(plan['night_start_utc'], plan['night_end_utc'])
        self.assertGreaterEqual(plan['moon_illumination_pct'], 0.0)
        self.assertLessEqual(plan['moon_illumination_pct'], 100.0)
        self.assertIn('generated_at', plan)
        self.assertNotIn('excluded', plan, "excluded is explain-only")

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_defaults_to_tonight(self, config):
        """Without ?date, the plan is for the night in progress at the telescope."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        cnx.close()

        plan = self._plan('scope_id=1')

        expected = night.night_date(datetime.datetime.now(datetime.timezone.utc), SCOPE_TZ)
        self.assertEqual(plan['night_date'], expected.isoformat())

    # --- visibility filtering -------------------------------------------

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_returns_visible_task_with_metadata(self, config):
        """A target transiting at night is planned, with its altitude/azimuth."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'HighUp')
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}')

        self.assertEqual(self._labels(plan), ['HighUp'])
        visibility = plan['items'][0]['visibility']
        self.assertGreater(visibility['altitude_deg'], 20.0)
        self.assertGreaterEqual(visibility['azimuth_deg'], 0.0)
        self.assertLess(visibility['sun_altitude_deg'], 0.0, "checked at night, not in daylight")
        self.assertGreaterEqual(visibility['moon_separation_deg'], 0.0)
        self.assertGreaterEqual(visibility['check_time_utc'], plan['night_start_utc'])
        self.assertLessEqual(visibility['check_time_utc'], plan['night_end_utc'])
        self.assertNotIn('project', plan['items'][0], "a task item carries no project key")

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_rejects_targets_the_sky_geometry_rules_out(self, config):
        """Too far south to clear min_alt, and too far south for the mount at all."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'HighUp')
        self._insert_task(cnx, 'TooLow', decl=-30.0)          # transit altitude ~8°
        self._insert_task(cnx, 'BelowMount', decl=-60.0)      # outside min_dec = -40
        # Mid-January the Sun sits near RA 19.7h, so this one is only ever up in daylight.
        self._insert_task(cnx, 'WrongSideOfSky', ra=19.7, decl=0.0)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}&explain=true')

        self.assertEqual(self._labels(plan), ['HighUp'])
        reasons = self._reasons(plan)
        self.assertEqual(reasons['TooLow'], 'below_min_altitude')
        self.assertEqual(reasons['BelowMount'], 'outside_mount_dec_range')
        self.assertEqual(reasons['WrongSideOfSky'], 'below_min_altitude')

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_honours_task_constraints(self, config):
        """min_alt, moon_distance, max_moon_phase and max_sun_alt each exclude a task."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'HighUp')
        self._insert_task(cnx, 'ImpossibleAltitude', min_alt=89.9)
        self._insert_task(cnx, 'MoonHater', moon_distance=180.0)
        self._insert_task(cnx, 'MoonlightHater', max_moon_phase=-1)
        self._insert_task(cnx, 'DeepNightOnly', max_sun_alt=-90)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}&explain=true')

        self.assertEqual(self._labels(plan), ['HighUp'])
        reasons = self._reasons(plan)
        self.assertEqual(reasons['ImpossibleAltitude'], 'below_min_altitude')
        self.assertEqual(reasons['MoonHater'], 'moon_too_close')
        self.assertEqual(reasons['MoonlightHater'], 'moon_phase_too_bright')
        self.assertEqual(reasons['DeepNightOnly'], 'sun_too_high')

    # --- stage 1 (state, dates, coordinates, scope) ----------------------

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_explains_stage1_exclusions(self, config):
        """State, date window, missing coordinates: rejected before any astronomy."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._ensure_task_states(cnx)
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'HighUp')
        self._insert_task(cnx, 'InQueue', state=3)
        self._insert_task(cnx, 'Template', state=0)
        self._insert_task(cnx, 'NotYet', skip_before='2026-06-01 00:00:00')
        self._insert_task(cnx, 'Expired', skip_after='2025-06-01 00:00:00')
        self._insert_task(cnx, 'Nowhere', ra=None, decl=None)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}&explain=true')

        self.assertEqual(sorted(self._labels(plan)), ['HighUp', 'InQueue'])
        reasons = self._reasons(plan)
        self.assertEqual(reasons['Template'], 'wrong_state')
        self.assertEqual(reasons['NotYet'], 'outside_date_window')
        self.assertEqual(reasons['Expired'], 'outside_date_window')
        self.assertEqual(reasons['Nowhere'], 'missing_coordinates')

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_explain_skips_finished_tasks(self, config):
        """
        Explain mode says nothing about DONE tasks.

        They are never planned and never asked about, and on a real archive
        they outnumber everything else - reporting them would make the excluded
        list grow with the archive instead of with the backlog.
        """
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._ensure_task_states(cnx)
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'HighUp')
        self._insert_task(cnx, 'AlreadyDone', state=6)
        self._insert_task(cnx, 'Template', state=0)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}&explain=true')

        self.assertEqual(self._labels(plan), ['HighUp'])
        reasons = self._reasons(plan)
        self.assertNotIn('AlreadyDone', reasons)
        self.assertEqual(reasons['Template'], 'wrong_state',
                         "other unplannable states are still explained")

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_explain_does_not_change_the_plan(self, config):
        """
        The SQL pre-filter and the Python classifier must agree.

        explain=true drops the SQL WHERE clauses and lets Python do the
        rejecting; the planned items have to come out identical either way.
        """
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._ensure_task_states(cnx)
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'HighUp')
        self._insert_task(cnx, 'AlreadyDone', state=6)
        self._insert_task(cnx, 'NotYet', skip_before='2026-06-01 00:00:00')
        self._insert_task(cnx, 'BelowMount', decl=-60.0)
        filter_id = self._insert_filter(cnx, 'NL')
        project_id = self._insert_project(cnx, 'Pending')
        self._insert_subframe(cnx, project_id, filter_id)
        done_id = self._insert_project(cnx, 'Finished')
        self._insert_subframe(cnx, done_id, filter_id, count=10, goal_count=10)
        cnx.close()

        plain = self._plan(f'scope_id=1&date={NIGHT}')
        explained = self._plan(f'scope_id=1&date={NIGHT}&explain=true')

        self.assertEqual(plain['items'], explained['items'])
        self.assertTrue(explained['excluded'])

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_is_scoped_to_one_telescope(self, config):
        """Tasks on another telescope are never planned."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._prepare_scope(cnx, scope_id=2)
        self._insert_task(cnx, 'Ours', scope_id=1)
        self._insert_task(cnx, 'Theirs', scope_id=2)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}&explain=true')

        self.assertEqual(self._labels(plan), ['Ours'])
        self.assertNotIn('Theirs', self._reasons(plan))

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_user_filter(self, config):
        """user_id narrows the plan to that user's tasks and project memberships."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'Mine', user_id=1)
        self._insert_task(cnx, 'Yours', user_id=2)
        filter_id = self._insert_filter(cnx, 'NL')
        mine = self._insert_project(cnx, 'MyProject', user_id=1)
        self._insert_subframe(cnx, mine, filter_id)
        yours = self._insert_project(cnx, 'YourProject', user_id=2)
        self._insert_subframe(cnx, yours, filter_id)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}&user_id=1')

        self.assertEqual(self._labels(plan), ['Mine'])
        self.assertEqual(self._labels(plan, kind='project'), ['MyProject'])

    # --- projects --------------------------------------------------------

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_includes_projects_with_pending_work(self, config):
        """Projects are planned like tasks, carrying only the subframes still to shoot."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        on_scope = self._insert_filter(cnx, 'NL')
        off_scope = self._insert_filter(cnx, 'NHa', on_scope_id=None)

        pending = self._insert_project(cnx, 'Pending')
        self._insert_subframe(cnx, pending, on_scope, count=3, goal_count=10)
        self._insert_subframe(cnx, pending, on_scope, count=10, goal_count=10)   # done
        self._insert_subframe(cnx, pending, on_scope, count=0, goal_count=10, active=False)

        self._insert_project(cnx, 'NoSubframes')
        finished = self._insert_project(cnx, 'Finished')
        self._insert_subframe(cnx, finished, on_scope, count=10, goal_count=10)
        wrong_filter = self._insert_project(cnx, 'WrongFilter')
        self._insert_subframe(cnx, wrong_filter, off_scope)
        self._insert_project(cnx, 'Inactive', active=False)
        self._insert_project(cnx, 'Ended', end_date='2025-12-31')
        self._insert_project(cnx, 'NotStarted', start_date='2026-06-01')
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}&explain=true')

        self.assertEqual(self._labels(plan, kind='project'), ['Pending'])
        project = plan['items'][0]['project']
        self.assertNotIn('task', plan['items'][0], "a project item carries no task key")
        self.assertEqual(len(project['subframes']), 1, "only the pending subframe is returned")
        self.assertEqual(project['subframes'][0]['count'], 3)
        self.assertEqual(project['subframes'][0]['filter']['short_name'], 'NL')
        self.assertEqual(project['user_ids'], [])

        reasons = self._reasons(plan)
        self.assertEqual(reasons['NoSubframes'], 'already_complete')
        self.assertEqual(reasons['Finished'], 'already_complete')
        self.assertEqual(reasons['WrongFilter'], 'filter_not_on_scope')
        self.assertEqual(reasons['Inactive'], 'wrong_state')
        self.assertEqual(reasons['Ended'], 'outside_date_window')
        self.assertEqual(reasons['NotStarted'], 'outside_date_window')

    # --- ordering, verbs, errors -----------------------------------------

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_orders_by_priority_then_kind(self, config):
        """Highest priority first; tasks before projects on a tie."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'LowPri', priority=1)
        self._insert_task(cnx, 'HighPri', priority=9)
        self._insert_task(cnx, 'MidPri', priority=5)
        filter_id = self._insert_filter(cnx, 'NL')
        project_id = self._insert_project(cnx, 'MidPriProject', priority=5)
        self._insert_subframe(cnx, project_id, filter_id)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}')

        self.assertEqual(plan['strategy'], 'priority')
        self.assertEqual(self._item_labels(plan),
                         ['HighPri', 'MidPri', 'MidPriProject', 'LowPri'])

        # The default is priority, so asking for it explicitly changes nothing.
        explicit = self._plan(f'scope_id=1&date={NIGHT}&strategy=priority')
        self.assertEqual(explicit['items'], plan['items'])

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_setting_first_orders_west_to_east(self, config):
        """
        strategy=setting_first runs the sky west to east.

        On this night local sidereal time at the middle of the night is around
        7-8h, so RA 4h is already heading down while RA 11h is still climbing:
        the setting one has to be shot first or not at all. Priority is
        deliberately the reverse of the sky order here, so the two strategies
        cannot accidentally agree.
        """
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'Setting', ra=4.0, priority=1)
        self._insert_task(cnx, 'Transiting', ra=7.5, priority=5)
        self._insert_task(cnx, 'Rising', ra=11.0, priority=9)
        cnx.close()

        by_sky = self._plan(f'scope_id=1&date={NIGHT}&strategy=setting_first')
        by_priority = self._plan(f'scope_id=1&date={NIGHT}')

        self.assertEqual(by_sky['strategy'], 'setting_first')
        self.assertEqual(self._item_labels(by_sky), ['Setting', 'Transiting', 'Rising'])
        self.assertEqual(self._item_labels(by_priority), ['Rising', 'Transiting', 'Setting'])
        # Same plan either way - the strategy only decides the order.
        self.assertEqual(sorted(self._item_labels(by_sky)),
                         sorted(self._item_labels(by_priority)))

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_setting_first_handles_ra_wraparound(self, config):
        """
        Sky order is relative to the night, not to the 0h/24h RA origin.

        With sidereal time around 7-8h at midnight, RA 23h rises late and RA 5h
        sets early; ordering on raw RA would put 23h last by sheer numeric
        accident, and get it right for the wrong reason. RA 13h is the case that
        tells the two apart: numerically it sits between them, but in the sky
        it is the last of the three to come round.
        """
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'RA5', ra=5.0)
        self._insert_task(cnx, 'RA13', ra=13.0)
        self._insert_task(cnx, 'RA23', ra=23.0)
        cnx.close()

        plan = self._plan(f'scope_id=1&date={NIGHT}&strategy=setting_first')

        self.assertEqual(self._item_labels(plan), ['RA23', 'RA5', 'RA13'])

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_unknown_strategy(self, config):
        """An unrecognised strategy is rejected, not silently ignored."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        self._plan(f'scope_id=1&date={NIGHT}&strategy=whatever', expect=422)

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_post_matches_get(self, config):
        """POST takes the same parameters in the body and answers the same."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        cnx = self._db()
        self._prepare_scope(cnx)
        self._insert_task(cnx, 'HighUp')
        cnx.close()

        response = self.app.post(
            '/api/night-plan',
            data=json.dumps({'scope_id': 1, 'date': NIGHT}),
            headers=self.headers)
        self.assertEqual(response.status_code, 200)
        posted = json.loads(response.data)

        self.assertEqual(posted['items'], self._plan(f'scope_id=1&date={NIGHT}')['items'])

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_unknown_telescope(self, config):
        """An unknown scope_id is a 404, not an empty plan."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        self._plan(f'scope_id=987&date={NIGHT}', expect=404)

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_telescope_without_location(self, config):
        """A telescope with no lat/lon can't be planned for: 400, with a reason."""
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        data = self._plan(f'scope_id=1&date={NIGHT}', expect=400)
        self.assertIn('lat/lon', data['message'])

    @use_repository(load_test_data="tests/test-data-basic.psql")
    def test_night_plan_invalid_date_format(self, config):
        os.environ['HEVELIUS_DB_NAME'] = config['database']
        self._plan('scope_id=1&date=invalid-date', expect=422)

    def test_night_plan_missing_scope(self):
        """scope_id stays required and explicit - never defaulted from preferences."""
        response = self.app.get('/api/night-plan', headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_night_plan_no_auth(self):
        response = self.app.get('/api/night-plan?scope_id=1')
        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main()
