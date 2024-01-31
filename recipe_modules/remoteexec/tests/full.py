# -*- coding: utf-8 -*-
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
