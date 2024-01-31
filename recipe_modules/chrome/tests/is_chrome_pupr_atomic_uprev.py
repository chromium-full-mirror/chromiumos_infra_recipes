# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.chrome.tests.is_chrome_pupr_atomic_uprev import \
  IsChromePuprAtomicUprevProperties

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


GERRIT_HOST = 'gerrit.host.test'
INTERNAL_GERRIT_HOST = 'chrome-internal-review.googlesource.com'
CHANGE_NUM = 12345
PROJECT_NAME = 'chromiumos/overlays/chromiumos-overlay'

PROPERTIES = IsChromePuprAtomicUprevProperties


def RunSteps(api, properties):
  gerrit_host = properties.gerrit_host or GERRIT_HOST

  gerrit_changes = [GerritChange(host=gerrit_host, change=CHANGE_NUM)]

  api.assertions.assertEqual(1, len(gerrit_changes))

  ret = api.chrome.is_chrome_pupr_atomic_uprev(gerrit_changes[0])
  api.assertions.assertEqual(properties.expected_result, ret)


def GenTests(api):

  # Ensure that the atomic uprev triggers
  yield api.test(
      'basic',
      api.properties(expected_result=True),
      api.step_data(
          'read git footers',
          stdout=api.raw_io.output('pupr:chromeos-base/lacros-ash-atomic')),
      api.gerrit.set_gerrit_fetch_changes_response(
          '', [GerritChange(host=GERRIT_HOST, change=CHANGE_NUM)], {
              CHANGE_NUM: {
                  'project': PROJECT_NAME,
                  'branch': 'main',
                  'topic': 'chromeos-base/lacros-ash-atomic',
                  'files': {
                      'chromeos-base/chromeos-chrome/chromeos-chrome-9999.ebuild':
                          {},
                  }
              },
          }),
  )

  yield api.test(
      'incorrect-host',
      api.properties(expected_result=False, gerrit_host=INTERNAL_GERRIT_HOST),
  )

  yield api.test(
      'incorrect-topic',
      api.properties(expected_result=False),
      api.step_data(
          'read git footers',
          stdout=api.raw_io.output('pupr:chromeos-base/lacros-ash-atomic')),
      api.gerrit.set_gerrit_fetch_changes_response(
          '', [GerritChange(host=GERRIT_HOST, change=CHANGE_NUM)], {
              CHANGE_NUM: {
                  'project': PROJECT_NAME,
                  'branch': 'main',
                  'topic': 'INCORRECT_TOPIC',
                  'files': {
                      'foo/bar/bar.ebuild': {},
                  }
              },
          }),
  )

  yield api.test(
      'incorrect-cq-cl-tag',
      api.properties(expected_result=False),
      api.step_data('read git footers',
                    stdout=api.raw_io.output('INCORRECT_CQ_CL_TAG')),
  )

  yield api.test(
      'empty-cq-cl-tag',
      api.properties(expected_result=False),
      api.step_data('read git footers', stdout=api.raw_io.output('')),
  )

  yield api.test(
      'incorrect-files',
      api.properties(expected_result=False),
      api.step_data(
          'read git footers',
          stdout=api.raw_io.output('pupr:chromeos-base/lacros-ash-atomic')),
      api.gerrit.set_gerrit_fetch_changes_response(
          '', [GerritChange(host=GERRIT_HOST, change=CHANGE_NUM)], {
              CHANGE_NUM: {
                  'project': PROJECT_NAME,
                  'branch': 'main',
                  'topic': 'chromeos-base/lacros-ash-atomic',
                  'files': {
                      'foo/bar/bar.ebuild': {},
                  }
              },
          }),
  )
