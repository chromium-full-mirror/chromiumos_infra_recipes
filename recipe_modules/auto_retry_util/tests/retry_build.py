# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Dict

import json

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/buildbucket',
    'auto_retry_util',
    'gerrit',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  build = api.buildbucket.build
  build.input.properties['$recipe_engine/cq'] = {
      'runMode': api.properties.get('runMode', 'FULL_RUN')
  }

  api.auto_retry_util.retry_build(
      build,
      retryable_builders=api.properties.get('retryable_builders',
                                            ['builderA', 'builderB']),
      retryable_test_suites=api.properties.get('retryable_test_suites',
                                               ['suite1', 'suite2']),
  )


def GenTests(api):

  def check_labels(
      build_id: int,
      change_id: int,
      labels: Dict[str, int],
  ):
    """Check the call to the Gerrit API to add labels to a change.

    Args:
      build_id: The id of the build being retried.
      change_id: The id of the change that got labels added.
      labels: The labels being set.
    """
    return api.post_process(
        post_process.StepCommandContains,
        f'retry build {build_id}.set labels on CL {change_id}.curl https://chromium.googlesource.com/changes/{change_id}/revisions/current/review',
        [
            json.dumps({'labels': labels}),
            f'https://chromium.googlesource.com/changes/{change_id}/revisions/current/review'
        ],
    )

  def check_comment(
      build_id: int,
      change_id: int,
      comment: str,
  ):
    """Check the call to the Gerrit API to add a comment to a change.

    Args:
      build_id: The id of the build being retried.
      change_id: The id of the change that got the comment added.
      comment: The comment added.
    """
    return api.post_process(
        post_process.StepCommandContains,
        f'retry build {build_id}.add comment on CL {change_id}.curl https://chromium.googlesource.com/changes/{change_id}/revisions/current/review',
        [
            json.dumps(
                {'comments': {
                    '/PATCHSET_LEVEL': [{
                        'message': comment
                    }]
                }}),
            f'https://chromium.googlesource.com/changes/{change_id}/revisions/current/review'
        ],
    )

  expected_comment = '''The previous build (https://cr-buildbucket.appspot.com/build/123) is being automatically retried for the following reasons:
- Some child builders are now retryable:builderA, builderB
- Some tests are now retryable:suite1, suite2

Did you notice a bug or UX issue with this retry? Please provide feedback: go/cros-auto-retry-bug.
'''
  eligible_value_dict = {
      456: {
          'change_number': 456,
          'labels': {
              'Commit-Queue': {
                  'optional': True,
                  'all': [{
                      '_account_id': 1234567,
                      'value': 0
                  }, {
                      '_account_id': 2345678,
                      'value': 0
                  }],
                  'values': {
                      ' 0': 'Not ready',
                      '+1': 'Dry run',
                      '+2': 'Commit'
                  }
              },
          }
      },
      789: {
          'change_number': 789,
          'labels': {
              'Commit-Queue': {
                  'optional': True,
                  'all': [{
                      '_account_id': 1234567,
                      'value': 0
                  }, {
                      '_account_id': 2345678,
                      'value': 0
                  }],
                  'values': {
                      ' 0': 'Not ready',
                      '+1': 'Dry run',
                      '+2': 'Commit'
                  }
              },
          }
      },
  }

  gerrit_changes = [
      GerritChange(
          host='chromium.googlesource.com',
          project='projectA',
          change=456,
          patchset=1,
      ),
      GerritChange(
          host='chromium.googlesource.com',
          project='projectB',
          change=789,
          patchset=4,
      ),
  ]

  retryable_build = api.test_util.test_orchestrator(
      build_id=123,
      cq=True,
      status='FAILURE',
      create_time=11,
      gerrit_changes=gerrit_changes,
  )

  yield api.test(
      'retry-build',
      retryable_build.build,
      api.auto_retry_util.enable_retries(),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'retry build {retryable_build.message.id}', gerrit_changes,
          eligible_value_dict,
          step_name=f'fetch changes for {retryable_build.message.id}'),
      check_labels(build_id=123, change_id=456, labels={'Commit-Queue': 2}),
      check_labels(build_id=123, change_id=789, labels={'Commit-Queue': 2}),
      check_comment(build_id=123, change_id=456, comment=expected_comment),
      check_comment(build_id=123, change_id=789, comment=expected_comment),
      api.post_process(post_process.DropExpectation),
  )

  # The orchestrator being retried was dry run.
  yield api.test(
      'orchestrator-dry-run',
      retryable_build.build,
      api.auto_retry_util.enable_retries(),
      api.properties(
          runMode='DRY_RUN',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'retry build {retryable_build.message.id}', gerrit_changes,
          eligible_value_dict,
          step_name=f'fetch changes for {retryable_build.message.id}'),
      check_labels(build_id=123, change_id=456, labels={'Commit-Queue': 1}),
      check_labels(build_id=123, change_id=789, labels={'Commit-Queue': 1}),
      check_comment(build_id=123, change_id=456, comment=expected_comment),
      check_comment(build_id=123, change_id=789, comment=expected_comment),
      api.post_process(post_process.DropExpectation),
  )

  # The auto retrier is being dry run.
  yield api.test(
      'dry-run',
      retryable_build.build,
      api.properties(**{'$chromeos/auto_retry_util': {
          'enable_retries': False
      }}),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'retry build {retryable_build.message.id} (dry_run)', gerrit_changes,
          eligible_value_dict,
          step_name=f'fetch changes for {retryable_build.message.id}'),
      api.post_process(post_process.DoesNotRunRE, '.*add comment on CL.*'),
      api.post_process(post_process.DoesNotRunRE, '.*set labels on CL.*'),
      api.post_process(post_process.DropExpectation),
  )

  already_retried_value_dict = {
      456: {
          'change_number': 456,
          'labels': {
              'Commit-Queue': {
                  'optional': True,
                  'all': [{
                      '_account_id': 1234567,
                      'value': 0
                  }, {
                      '_account_id': 2345678,
                      'value': 2
                  }],
                  'values': {
                      ' 0': 'Not ready',
                      '+1': 'Dry run',
                      '+2': 'Commit'
                  }
              },
          }
      },
      789: {
          'change_number': 789,
          'labels': {
              'Commit-Queue': {
                  'optional': True,
                  'all': [{
                      '_account_id': 1234567,
                      'value': 1
                  }, {
                      '_account_id': 2345678,
                      'value': 0
                  }],
                  'values': {
                      ' 0': 'Not ready',
                      '+1': 'Dry run',
                      '+2': 'Commit'
                  }
              },
          }
      },
  }

  yield api.test(
      'already-retried',
      retryable_build.build,
      api.auto_retry_util.enable_retries(),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'retry build {retryable_build.message.id}', gerrit_changes,
          already_retried_value_dict,
          step_name=f'fetch changes for {retryable_build.message.id}'),
      api.post_process(post_process.DoesNotRunRE, '.*add comment on CL.*'),
      api.post_process(post_process.DoesNotRunRE, '.*set labels on CL.*'),
      api.post_process(post_process.DropExpectation),
  )

  # The already retried orchestrator was dry run.
  yield api.test(
      'already-retried-dry-run',
      retryable_build.build,
      api.auto_retry_util.enable_retries(),
      api.properties(
          runMode='DRY_RUN',
      ),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'retry build {retryable_build.message.id}', gerrit_changes,
          already_retried_value_dict,
          step_name=f'fetch changes for {retryable_build.message.id}'),
      api.post_process(post_process.DoesNotRunRE, '.*add comment on CL.*'),
      api.post_process(post_process.DoesNotRunRE, '.*set labels on CL.*'),
      api.post_process(post_process.DropExpectation),
  )

  many_builds_and_tests_comment = '''The previous build (https://cr-buildbucket.appspot.com/build/123) is being automatically retried for the following reasons:
- Some child builders are now retryable:builder0, builder1, builder2, builder3, builder4,...
- Some tests are now retryable:suite0, suite1, suite2, suite3, suite4,...

Did you notice a bug or UX issue with this retry? Please provide feedback: go/cros-auto-retry-bug.
'''
  yield api.test(
      'many-builds-and-tests',
      retryable_build.build,
      api.auto_retry_util.enable_retries(),
      api.gerrit.set_gerrit_fetch_changes_response(
          f'retry build {retryable_build.message.id}', gerrit_changes,
          eligible_value_dict,
          step_name=f'fetch changes for {retryable_build.message.id}'),
      api.properties(
          retryable_builders=[f'builder{i}' for i in range(10)],
          retryable_test_suites=[f'suite{i}' for i in range(10)],
      ),
      check_comment(build_id=123, change_id=456,
                    comment=many_builds_and_tests_comment),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-builds-or-tests',
      retryable_build.build,
      api.auto_retry_util.enable_retries(),
      api.properties(
          retryable_builders=[],
          retryable_test_suites=[],
      ),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
