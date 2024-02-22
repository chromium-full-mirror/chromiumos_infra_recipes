# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Testing when the changes were submitted."""

import datetime
from recipe_engine import post_process
from PB.recipe_modules.chromeos.lfg_util.examples.test import \
  LatestSubmittedTimeProperties
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'depot_tools/gerrit',
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/time',
    'lfg_util',
]

PROPERTIES = LatestSubmittedTimeProperties


def RunSteps(api, properties):
  host = 'chromium-review.googlesource.com'
  project = 'kernel'
  changes = [
      GerritChange(change=c, host=host, project=project, patchset=1)
      for c in properties.change_ids
  ]
  kwargs = {}
  if properties.expected_submission:
    submit_time = str(api.time.utcnow() - datetime.timedelta(hours=5))
    kwargs['submitted'] = submit_time + '000'
  gerrit_response_data = api.gerrit.test_api.get_one_change_response_data(
      change_number=properties.change_ids[0],
      patchset=properties.patchset or 1, **kwargs)
  step_test_data = lambda: gerrit_response_data
  result = api.lfg_util.latest_submission_time(gerrit_changes=changes,
                                              step_test_data=step_test_data)
  api.assertions.assertEqual(str(result), properties.expected_result)


def GenTests(api):
  yield api.test(
      'not-submitted',
      api.properties(expected_result='None', change_ids=[123]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'gerrit-error',
      api.properties(expected_result='None', change_ids=[123], patchset=2),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'submitted',
      api.properties(expected_result='2012-05-14 07:53:21.500000',
                     change_ids=[123], expected_submission=True),
      api.post_process(post_process.DropExpectation),
  )
