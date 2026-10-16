import os
import unittest
from unittest import mock

from platform_app import postproc_embedded as pe


class EmbeddedPostprocWantedTests(unittest.TestCase):
    def test_explicit_on_wins(self):
        with mock.patch.dict(os.environ, {"RPG_EMBEDDED_POSTPROC": "1"}):
            self.assertTrue(pe.embedded_postproc_wanted())

    def test_explicit_off_wins(self):
        with mock.patch.dict(os.environ, {"RPG_EMBEDDED_POSTPROC": "0", "RPG_DEPLOYMENT_MODE": "local"}):
            self.assertFalse(pe.embedded_postproc_wanted())

    def test_off_under_pytest_by_default(self):
        with mock.patch.dict(os.environ, {"RPG_EMBEDDED_POSTPROC": "", "RPG_DEPLOYMENT_MODE": "local"}):
            self.assertFalse(pe.embedded_postproc_wanted())

    def test_local_mode_on_outside_tests(self):
        env = {"RPG_EMBEDDED_POSTPROC": "", "RPG_DEPLOYMENT_MODE": "local"}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            self.assertTrue(pe.embedded_postproc_wanted())

    def test_server_mode_off(self):
        env = {"RPG_EMBEDDED_POSTPROC": "", "RPG_DEPLOYMENT_MODE": "server"}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            self.assertFalse(pe.embedded_postproc_wanted())

    def test_worker_module_importable(self):
        from scripts.run_postproc_worker import consume
        self.assertTrue(callable(consume))
