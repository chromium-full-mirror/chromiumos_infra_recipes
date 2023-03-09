# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'chrome',
    'gerrit',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

GERRIT_HOST = 'gerrit.host.test'
CHANGE_NUM = 12345
PROJECT_NAME = 'chromiumos/overlays/chromiumos-overlay'

PROPERTIES = {
    'expected_result':
        Property(
            help='Expected return value from is_chrome_pupr_atomic_uprev().',
            default=True),
}


def RunSteps(api, expected_result):
  gerrit_changes = [GerritChange(host=GERRIT_HOST, change=CHANGE_NUM)]

  api.assertions.assertEqual(1, len(gerrit_changes))

  ret = api.chrome.is_chrome_pupr_atomic_uprev(gerrit_changes[0])
  api.assertions.assertEqual(expected_result, ret)


def GenTests(api):

  # Ensure that the atomic uprev triggers
  yield api.test(
      'basic',
      api.properties(expected_result=True),
      api.gerrit.simulated_topic("chromeos-base/lacros-ash-atomic", GERRIT_HOST,
                                 CHANGE_NUM),
      api.step_data(
          'read git footers',
          stdout=api.raw_io.output('pupr:chromeos-base/lacros-ash-atomic')),
      api.gerrit.set_gerrit_fetch_changes_response(
          '', [GerritChange(host=GERRIT_HOST, change=CHANGE_NUM)], {
              CHANGE_NUM: {
                  'project': PROJECT_NAME,
                  'branch': 'main',
                  'files': {
                      'chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild':
                          {},
                  }
              },
          }),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'incorrect-topic',
      api.properties(expected_result=False),
      api.gerrit.simulated_topic("INCORRECT_TOPIC", GERRIT_HOST, CHANGE_NUM),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'incorrect-cq-cl-tag',
      api.properties(expected_result=False),
      api.gerrit.simulated_topic("chromeos-base/lacros-ash-atomic", GERRIT_HOST,
                                 CHANGE_NUM),
      api.step_data('read git footers',
                    stdout=api.raw_io.output('INCORRECT_CQ_CL_TAG')),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'empty-cq-cl-tag',
      api.properties(expected_result=False),
      api.gerrit.simulated_topic("chromeos-base/lacros-ash-atomic", GERRIT_HOST,
                                 CHANGE_NUM),
      api.step_data('read git footers', stdout=api.raw_io.output('')),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'incorrect-files',
      api.properties(expected_result=False),
      api.gerrit.simulated_topic("chromeos-base/lacros-ash-atomic", GERRIT_HOST,
                                 CHANGE_NUM),
      api.step_data(
          'read git footers',
          stdout=api.raw_io.output('pupr:chromeos-base/lacros-ash-atomic')),
      api.gerrit.set_gerrit_fetch_changes_response(
          '', [GerritChange(host=GERRIT_HOST, change=CHANGE_NUM)], {
              CHANGE_NUM: {
                  'project': PROJECT_NAME,
                  'branch': 'main',
                  'files': {
                      'foo/bar/bar.ebuild': {},
                  }
              },
          }),
      api.post_process(post_process.StatusSuccess),
  )
