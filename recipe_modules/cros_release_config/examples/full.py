# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import datetime

from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import CrosReleaseConfigProperties
from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import Email
from PB.recipe_modules.chromeos.cros_release_config.examples.full import TestProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_release_config',
    'cros_schedule',
    'repo',
    'test_util',
]



def expected_config(*blocks):
  return ''.join(blocks)


MAIN_BLOCK = '''builders {
  milestone {
    number: -1
    branch_name: "main"
  }
  build_schedule: "0 1 * * *"
}
'''

BLOCK_1 = '''builders {
  milestone {
    number: 1
    branch_name: "release-R01-00001.B"
  }
}
'''

BLOCK_2 = '''builders {
  milestone {
    number: 2
    branch_name: "release-R02-00002.B"
  }
}
'''

BLOCK_3 = '''builders {
  milestone {
    number: 3
    branch_name: "release-R03-00003.B"
  }
}
'''

BLOCK_NEW = '''builders {
  milestone {
    number: %(number)d
    branch_name: "%(branch_name)s"
  }%(expiration_block)s
  android_branches {
    key: "android-vm-tm"
    value: "git_tm-arc-m%(number)s"
  }
}
'''

EXPIRATION_SECTION_TEMPLATE = '''
  expiration_date {
    value: "%s"
  }'''

BLOCK_NEW_STABILIZE = '''builders {
  milestone {
    branch_name: "%s"
  }%s
}
'''

BLOCK_NEW_FIRMWARE = '''builders {
  milestone {
    number: %(number)d
    branch_name: "%(branch_name)s"
  }
}
'''


# Return a block of config to be included in textpb expecations.
def new_block(number, branch_name, expiration_date=None):
  expiration_block = ''
  if expiration_date:
    expiration_block = EXPIRATION_SECTION_TEMPLATE % expiration_date
  return BLOCK_NEW % {
      'number': number,
      'branch_name': branch_name,
      'expiration_block': expiration_block,
  }


# Return a block of config to be included in textpb expecations.
def new_stabilize_block(branch_name, expiration_date=None):
  expiration_block = ''
  if expiration_date:
    expiration_block = EXPIRATION_SECTION_TEMPLATE % expiration_date
  return BLOCK_NEW_STABILIZE % (branch_name, expiration_block)


# Return a block of config to be included in textpb expecations.
def new_firmware_block(number, branch_name):
  return BLOCK_NEW_FIRMWARE % {
      'number': number,
      'branch_name': branch_name,
  }


BLOCK_EXPIRATION = '''builders {
  milestone {
    number: 40
    branch_name: "release-R40-00040.B"
  }
  expiration_date {
    value: "2100-01-01"
  }
}
'''

EXPECTED_WRITE_PRUNED_TEMPLATE = '''builders {
  milestone {
    number: -1
    branch_name: "main"
  }
  build_schedule: "0 1 * * *"
}
builders {
  milestone {
    number: %d
    branch_name: "%s"
  }
}
builders {
  milestone {
    number: 3
    branch_name: "release-R03-00003.B"
  }
}
'''

PROPERTIES = TestProperties


def RunSteps(api, properties):
  api.cros_release_config.update_config(properties.branch,
                                        auto_submit=properties.auto_submit,
                                        dryrun=properties.dryrun)


def GenTests(api):
  branch = 'release-R05-00004.B'
  branch_milestone = 5

  yield api.test(
      'basic',
      api.properties(
          **{
              'branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='jackneus@google.com')],
                      ccs=[Email(
                          email='engeg@google.com')], keep_n_milestones=4)
          }),
      api.step_data(
          'update config.fetch chromiumdash schedule.curl fetch_milestone_schedule',
          api.raw_io.stream_output(
              api.cros_schedule.test_chromiumdash_fetch_response(
                  start_mstone=5,
                  fetch_n=1,
                  ltr_last_refresh_date='2023-01-01T00:00:00',
                  late_stable_date='2022-11-01T00:00:00',
              ))),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/release_builders.textpb', [
              expected_config(MAIN_BLOCK, BLOCK_EXPIRATION,
                              new_block(branch_milestone, branch, '2023-01-15'),
                              BLOCK_3, BLOCK_2, BLOCK_1)
          ]))

  six_months_out = (datetime.datetime.today() +
                    datetime.timedelta(days=30 * 6)).strftime('%Y-%m-%d')

  one_year_out = (datetime.datetime.today() +
                  datetime.timedelta(days=366)).strftime('%Y-%m-%d')

  yield api.test(
      'stabilize-branch',
      api.properties(
          **{
              'branch':
                  'stabilize-12345.B',
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='jackneus@google.com')],
                      ccs=[Email(
                          email='engeg@google.com')], keep_n_milestones=4)
          }),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/stabilize_builders.textpb', [
              expected_config(
                  MAIN_BLOCK, BLOCK_EXPIRATION,
                  new_stabilize_block('stabilize-12345.B', six_months_out),
                  BLOCK_3, BLOCK_2, BLOCK_1)
          ]), api.post_process(post_process.DropExpectation))

  yield api.test(
      'firmware-branch',
      api.properties(
          **{
              'branch':
                  'firmware-R126-12345.B',
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='jbettis@google.com')], ccs=[
                          Email(email='chromeos-firmware@google.com')
                      ], keep_n_milestones=3)
          }),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/firmware_builders.textpb', [
              expected_config(MAIN_BLOCK, BLOCK_EXPIRATION,
                              new_firmware_block(126, 'firmware-R126-12345.B'),
                              BLOCK_3, BLOCK_2, BLOCK_1)
          ]),
      api.post_check(post_process.StepSuccess, 'update config'),
      api.post_process(post_process.DropExpectation),
  )

  # These branches won't be created in the future, but test them.
  yield api.test(
      'firmware-ec-branch',
      api.properties(
          **{
              'branch':
                  'firmware-ec-R126-12345.2.B',
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='jbettis@google.com')], ccs=[
                          Email(email='chromeos-firmware@google.com')
                      ], keep_n_milestones=3)
          }),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/firmware_builders.textpb', [
              expected_config(
                  MAIN_BLOCK, BLOCK_EXPIRATION,
                  new_firmware_block(126, 'firmware-ec-R126-12345.2.B'),
                  BLOCK_3, BLOCK_2, BLOCK_1)
          ]),
      api.post_check(post_process.StepSuccess, 'update config'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'firmware-milestone-branch',
      api.properties(
          **{
              'branch':
                  'firmware-R126-12345.2.B',
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='jbettis@google.com')], ccs=[
                          Email(email='chromeos-firmware@google.com')
                      ], keep_n_milestones=3)
          }),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/firmware_builders.textpb', [
              expected_config(
                  MAIN_BLOCK, BLOCK_EXPIRATION,
                  new_firmware_block(126, 'firmware-R126-12345.2.B'), BLOCK_3,
                  BLOCK_2, BLOCK_1)
          ]),
      api.post_check(post_process.StepSuccess, 'update config'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'firmware-branch-android',
      api.properties(
          **{
              'branch':
                  'firmware-android-foo-12345.678.B',
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='chromeos-firmware@google.com')]),
          }),
      api.post_check(post_process.StepSuccess,
                     'validate branch.validate firmware branch'),
      api.post_check(post_process.DoesNotRun, 'update config'))

  yield api.test(
      'bad-branch',
      api.properties(**{
          'branch': 'factory-foo.B',
      }),
      api.post_check(post_process.StepFailure, 'validate branch'),
      status='FAILURE',
  )

  yield api.test(
      'bad-release-branch',
      api.properties(**{
          'branch': 'release-foo.B',
      }),
      api.post_check(post_process.StepFailure,
                     'validate branch.validate release branch'),
      status='FAILURE',
  )

  yield api.test(
      'bad-firmware-branch',
      api.properties(**{
          'branch': 'firmware-foo.B',
      }),
      api.post_check(post_process.StepFailure,
                     'validate branch.validate firmware branch'),
      status='FAILURE',
  )

  yield api.test(
      'no-reviewers-no-autosubmit',
      api.properties(**{
          'branch': branch,
      }),
      api.post_check(post_process.StepFailure, 'validate CL settings'),
      status='FAILURE',
  )

  yield api.test('auto-submit',
                 api.properties(**{
                     'auto_submit': True,
                     'branch': branch,
                 }))

  yield api.test(
      'prune',
      api.properties(
          **{
              'auto_submit':
                  True,
              'branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(keep_n_milestones=2),
          }),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/release_builders.textpb', [
              expected_config(MAIN_BLOCK, BLOCK_EXPIRATION,
                              new_block(branch_milestone, branch, '2021-03-30'),
                              BLOCK_3)
          ]), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'with-build-creator',
      api.properties(**{
          'auto_submit': True,
          'branch': branch,
      }),
      api.test_util.test_build(
          created_by='user:fakedeveloper@chromium.org').build,
  )

  yield api.test(
      'with-build-creator-duplicate-email',
      api.properties(
          **{
              'branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='fakedeveloper@chromium.org')],
                      ccs=[Email(email='fakedeveloper@google.com')])
          }),
      api.test_util.test_build(
          created_by='user:fakedeveloper@chromium.org').build,
  )

  yield api.test(
      'dry-run-abandon-cl',
      api.properties(
          **{
              'dryrun':
                  True,
              'branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='jackneus@google.com')])
          }))

  yield api.test(
      'starline-branch',
      api.properties(
          **{
              'branch':
                  'stabilize-starline-54321.B',
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email='hardtmad@google.com')],
                      ccs=[Email(
                          email='bshai@google.com')], keep_n_milestones=4)
          }),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/stabilize_builders.textpb', [
              expected_config(
                  MAIN_BLOCK, BLOCK_EXPIRATION,
                  new_stabilize_block('stabilize-starline-54321.B',
                                      one_year_out), BLOCK_3, BLOCK_2, BLOCK_1)
          ]), api.post_process(post_process.DropExpectation))

  yield api.test(
      'stable-skipped-branch',
      api.properties(
          **{
              'branch':
                  'release-R153-16790.B',
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(
                          email='hardtmad@google.com')], keep_n_milestones=4),
          }),
      api.step_data(
          'update config.fetch chromiumdash schedule.curl fetch_milestone_schedule',
          api.raw_io.stream_output(
              api.cros_schedule.test_chromiumdash_fetch_response(
                  start_mstone=153, fetch_n=1, late_stable_date=None))),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/release_builders.textpb', [
              expected_config(MAIN_BLOCK, BLOCK_EXPIRATION,
                              new_block(153, 'release-R153-16790.B'), BLOCK_3,
                              BLOCK_2, BLOCK_1)
          ]), api.post_process(post_process.DropExpectation))

  yield api.test(
      'stable-eligible-branch',
      api.properties(
          **{
              'branch':
                  'release-R154-16815.B',
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(
                          email='hardtmad@google.com')], keep_n_milestones=4),
          }),
      api.step_data(
          'update config.fetch chromiumdash schedule.curl fetch_milestone_schedule',
          api.raw_io.stream_output(
              api.cros_schedule.test_chromiumdash_fetch_response(
                  start_mstone=154, fetch_n=1))),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/release_builders.textpb', [
              expected_config(
                  MAIN_BLOCK, BLOCK_EXPIRATION,
                  new_block(154, 'release-R154-16815.B', '2021-03-30'), BLOCK_3,
                  BLOCK_2, BLOCK_1)
          ]), api.post_process(post_process.DropExpectation))
