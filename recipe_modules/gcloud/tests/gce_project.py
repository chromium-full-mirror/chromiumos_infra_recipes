# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gcloud',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.assertions.assertEqual(
      str(api.gcloud._gce_project),
      api.properties.thaw()['expected_gce_project'])


def GenTests(api):

  yield api.test(
      'no-override',
      api.properties(**{
          'expected_gce_project': 'chromeos-bot',
      }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'override',
      api.properties(
          **{
              '$chromeos/gcloud': {
                  'gce_project': 'chromeos-bot-override',
              },
              'expected_gce_project': 'chromeos-bot-override',
          }),
      api.post_process(post_process.DropExpectation),
  )
