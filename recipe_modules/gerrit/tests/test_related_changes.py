# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.gerrit.tests.gerrit_test import GerritTestProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/step',
    'gerrit',
]


PROPERTIES = GerritTestProperties

gerrit_change = GerritChange(host='chromium-review.googlesource.com',
                             change=91827, patchset=1)

RELATED_OUTPUT = {
    'related': [{
        '_change_number': '321',
        'host': 'chromium-review.googlesource.com'
    }, {
        '_change_number': '432',
        'host': 'chromium-review.googlesource.com'
    }]
}
NO_RELATED_OUTPUT = {'related': []}


def RunSteps(api, properties):
  related = api.gerrit.gerrit_related_changes(properties.gerrit_change)
  if properties.expect_success:
    expected_related = json.loads(properties.read_text_output_str)['related']
  else:
    expected_related = []
  api.assertions.assertEqual(expected_related, related)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'related',
      api.properties(gerrit_change=gerrit_change,
                     read_text_output_str=json.dumps(RELATED_OUTPUT),
                     expect_success=True),
      api.gerrit.set_gerrit_related_changes(RELATED_OUTPUT),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-related',
      api.properties(gerrit_change=gerrit_change,
                     read_text_output_str=json.dumps(NO_RELATED_OUTPUT),
                     expect_success=True),
      api.gerrit.set_gerrit_related_changes(NO_RELATED_OUTPUT),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'fail-output-parse',
      api.properties(gerrit_change=gerrit_change, expect_success=False),
      api.gerrit.set_gerrit_related_changes({}, retcode=1),
      api.post_check(post_process.StepTextEquals, 'call gerrit_related_changes',
                     "couldn't parse output of related changes"),
      api.post_process(post_process.DropExpectation))
