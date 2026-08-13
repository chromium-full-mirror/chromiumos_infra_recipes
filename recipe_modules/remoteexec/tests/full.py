# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.remoteexec.remoteexec import RemoteexecProperties
from PB.recipe_modules.chromeos.remoteexec.tests.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'remoteexec',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):

  api.assertions.assertEqual(
      str(api.remoteexec.reclient_dir), properties.expected_reclient_dir)
  # Test that reclient_dir is cached rather than calling _ensure_reclient()
  # again.
  api.assertions.assertEqual(
      str(api.remoteexec.reclient_dir), properties.expected_reclient_dir)
  api.assertions.assertEqual(
      str(api.remoteexec.reproxy_cfg_file),
      properties.expected_reproxy_cfg_file)

  class FakeSolution:

    def __init__(self):
      self.custom_vars = None

  soln = FakeSolution()
  api.remoteexec.set_rbe_instance_hook(soln)

  if api.remoteexec._rbe_project:  # pylint: disable=protected-access
    api.assertions.assertEqual(
        soln.custom_vars.get('rbe_instance'),
        'projects/my-project/instances/my-instance')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/remoteexec':
                  RemoteexecProperties(
                      reproxy_cfg_file='reclient_cfgs/reproxy_config_1.cfg',
                      reclient_version='release',
                  )
          }),
      api.properties(
          TestInputProperties(
              expected_reclient_version='release',
              expected_reproxy_cfg_file='reclient_cfgs/reproxy_config_1.cfg',
              expected_reclient_dir='[START_DIR]/cipd/rbe',
          )),
  )

  yield api.test(
      'with_rbe_project',
      api.properties(
          **{
              '$chromeos/remoteexec':
                  RemoteexecProperties(
                      reproxy_cfg_file='reclient_cfgs/reproxy_config_1.cfg',
                      reclient_version='release',
                      rbe_project='my-project',
                      reapi_instance='my-instance',
                  )
          }),
      api.properties(
          TestInputProperties(
              expected_reclient_version='release',
              expected_reproxy_cfg_file='reclient_cfgs/reproxy_config_1.cfg',
              expected_reclient_dir='[START_DIR]/cipd/rbe',
          )),
  )
