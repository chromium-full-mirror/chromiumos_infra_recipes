# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_release_config',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from recipe_engine import post_process


def construct_legacy_config(*blocks):
  return """
  ...
  # BOT-TAG:RELEASES_START
  RELEASES = [%s  ]
  # BOT-TAG:RELEASES_END
  ...
""" % "".join(blocks)


LEGACY_BLOCK_NEW = """
      ('{}',
       ['kevin-android-pi-pre-flight-branch',
        'hatch-android-rvc-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
"""
LEGACY_BLOCK_4 = """
      # This is a branch.
      ('release-R04-13729.B',
       ['grunt-android-pi-pre-flight-branch',
        'hatch-android-rvc-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
"""

LEGACY_BLOCK_3 = """
      # This is another branch!

      ('release-R03-13597.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
"""

LEGACY_BLOCK_2 = """
      ('release-R02-13505.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
"""

LEGACY_BLOCK_1 = """

      # LTS branch, please do not delete. Contact: cros-lts-team@google.com.
      # BOT-TAG:NO_PRUNE
      ('release-R01-13421.B',
       ['grunt-android-pi-pre-flight-branch'],
       'chell-chrome-no-afdo-uprev-pre-flight-branch',
       ['orderfile-generate-toolchain',
        'orderfile-verify-toolchain'],
       ['benchmark-afdo-generate',
        'chrome-silvermont-release-afdo-verify',
        'chrome-airmont-release-afdo-verify',
        'chrome-broadwell-release-afdo-verify'],
       config_lib.LUCI_BUILDER_LTS_RELEASE ),
"""


def expected_config(*blocks):
  return "".join(blocks)


MAIN_BLOCK = """builders {
  milestone {
    number: -1
    branch_name: "main"
  }
  build_schedule: "0 1 * * *"
}
"""

BLOCK_1 = """builders {
  milestone {
    number: 1
    branch_name: "release-R01-00001.B"
  }
  build_schedule: "0 8 * * *"
}
"""

BLOCK_2 = """builders {
  milestone {
    number: 2
    branch_name: "release-R02-00002.B"
  }
  build_schedule: "0 9 * * *"
}
"""

BLOCK_3 = """builders {
  milestone {
    number: 3
    branch_name: "release-R03-00003.B"
  }
  build_schedule: "0 * * * *"
}
"""

BLOCK_NEW = """builders {
  milestone {
    number: %d
    branch_name: "%s"
  }
  build_schedule: "0 0 * * *"
}
"""

BLOCK_EXPIRATION = """builders {
  milestone {
    number: 40
    branch_name: "release-R40-00040.B"
  }
  build_schedule: "0 11 * * *"
  expiration_date {
    value: "2100-01-01"
  }
}
"""

EXPECTED_WRITE_PRUNED_TEMPLATE = """builders {
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
  build_schedule: "0 0 * * *"
}
builders {
  milestone {
    number: 3
    branch_name: "release-R03-00003.B"
  }
  build_schedule: "0 10 * * *"
}
"""

from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import (
    Email, CrosReleaseConfigProperties)
from PB.recipe_modules.chromeos.cros_release_config.examples.full import TestProperties

PROPERTIES = TestProperties


def RunSteps(api, properties):
  api.cros_release_config.update_config(properties.release_branch)


def GenTests(api):
  branch = 'release-R05-00004.B'
  branch_milestone = 5

  legacy_config_test_data = construct_legacy_config(LEGACY_BLOCK_2,
                                                    LEGACY_BLOCK_4,
                                                    LEGACY_BLOCK_3,
                                                    LEGACY_BLOCK_1)

  yield api.test(
      'basic',
      api.properties(
          **{
              'release_branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email="jackneus@google.com")],
                      ccs=[Email(
                          email="engeg@google.com")], keep_n_milestones=4)
          }),
      api.step_data('update legacy config.read config/chromeos_config.py',
                    api.file.read_raw(legacy_config_test_data)),
      api.post_process(post_process.StepCommandContains,
                       'update legacy config.write config/chromeos_config.py', [
                           construct_legacy_config(
                               LEGACY_BLOCK_NEW.format(branch), LEGACY_BLOCK_2,
                               LEGACY_BLOCK_4, LEGACY_BLOCK_3, LEGACY_BLOCK_1)
                       ]),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/release_builders.textpb', [
              expected_config(MAIN_BLOCK, BLOCK_EXPIRATION, BLOCK_NEW %
                              (branch_milestone, branch), BLOCK_3, BLOCK_2,
                              BLOCK_1)
          ]))

  yield api.test(
      'bad-branch',
      api.properties(**{
          'release_branch': 'release-foo.B',
      }),
      api.post_check(post_process.StepFailure, 'validate release_branch'),
  )

  yield api.test(
      'no-reviewers-no-autosubmit',
      api.properties(**{
          'release_branch': branch,
      }),
      api.post_check(post_process.StepFailure, 'validate CL settings'),
  )

  yield api.test(
      'auto-submit',
      api.properties(
          **{
              'release_branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(auto_submit=True),
          }),
      api.step_data('update legacy config.read config/chromeos_config.py',
                    api.file.read_raw(legacy_config_test_data)),
  )

  yield api.test(
      'prune',
      api.properties(
          **{
              'release_branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(auto_submit=True,
                                              keep_n_milestones=2),
          }),
      api.step_data('update legacy config.read config/chromeos_config.py',
                    api.file.read_raw(legacy_config_test_data)),
      api.post_process(post_process.StepCommandContains,
                       'update legacy config.write config/chromeos_config.py', [
                           construct_legacy_config(
                               LEGACY_BLOCK_NEW.format(branch), LEGACY_BLOCK_4,
                               LEGACY_BLOCK_1)
                       ]),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/release_builders.textpb', [
              expected_config(MAIN_BLOCK, BLOCK_EXPIRATION, BLOCK_NEW %
                              (branch_milestone, branch), BLOCK_3)
          ]))

  legacy_config_test_data = 'foo'
  yield api.test(
      'bad-legacy-config',
      api.properties(
          **{
              'release_branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(auto_submit=True,
                                              keep_n_milestones=2),
          }),
      api.step_data('update legacy config.read config/chromeos_config.py',
                    api.file.read_raw(legacy_config_test_data)),
      api.post_check(post_process.StepFailure,
                     'update legacy config.prune legacy config'),
  )

  legacy_config_test_data = '# BOT-TAG:RELEASES_START\nfoo\n# BOT-TAG:RELEASES_END'
  yield api.test(
      'bad-legacy-config2',
      api.properties(
          **{
              'release_branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(auto_submit=True,
                                              keep_n_milestones=2),
          }),
      api.step_data('update legacy config.read config/chromeos_config.py',
                    api.file.read_raw(legacy_config_test_data)),
      api.post_check(post_process.StepFailure,
                     'update legacy config.prune legacy config'),
  )

  legacy_config_test_data = """
  # BOT-TAG:RELEASES_START
  RELEASES = [
    (foo),
    (bar),
  ]
  # BOT-TAG:RELEASES_END'
  """
  yield api.test(
      'bad-legacy-config3',
      api.properties(
          **{
              'release_branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(auto_submit=True,
                                              keep_n_milestones=2),
          }),
      api.step_data('update legacy config.read config/chromeos_config.py',
                    api.file.read_raw(legacy_config_test_data)),
      api.post_check(post_process.StepFailure,
                     'update legacy config.prune legacy config'),
  )
