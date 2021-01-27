# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_release_config',
    'repo',
]
from recipe_engine import post_process

EXPECTED_LEGACY_WRITE_TEMPLATE = """
  ...
  # Start of RELEASES
  RELEASES = [
      ('{}',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),

      ('release-R89-13729.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),

      ('release-R88-13597.B',
       ['grunt-android-pi-pre-flight-branch'],
       '',
       [],
       [],
       config_lib.LUCI_BUILDER_LEGACY_RELEASE),
  ]
  # End of RELEASES
  ...
"""

EXPECTED_WRITE_TEMPLATE = """builders {
  milestone {
    number: -1
    branch_name: "main"
  }
  build_schedule: "0 1 * * *"
}
builders {
  milestone {
    number: 1
    branch_name: "release-R01-00001.B"
  }
  build_schedule: "0 8 * * *"
}
builders {
  milestone {
    number: 2
    branch_name: "release-R02-00002.B"
  }
  build_schedule: "0 9 * * *"
}
builders {
  milestone {
    number: 3
    branch_name: "release-R03-00003.B"
  }
  build_schedule: "0 10 * * *"
}
builders {
  milestone {
    number: %d
    branch_name: "%s"
  }
  build_schedule: "0 0 * * *"
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
builders {
  milestone {
    number: 2
    branch_name: "release-R02-00002.B"
  }
  build_schedule: "0 9 * * *"
}
"""

from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import (
    Email, CrosReleaseConfigProperties)
from PB.recipe_modules.chromeos.cros_release_config.examples.full import TestProperties

PROPERTIES = TestProperties


def RunSteps(api, properties):
  api.cros_release_config.update_config(properties.release_branch)


def GenTests(api):
  branch = 'release-R04-00004.B'
  branch_milestone = 4

  yield api.test(
      'basic',
      api.properties(
          **{
              'release_branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(
                      reviewers=[Email(email="jackneus@google.com")],
                      ccs=[Email(email="engeg@google.com")])
          }),
      api.post_process(post_process.StepCommandContains,
                       'update legacy config.write config/chromeos_config.py',
                       [EXPECTED_LEGACY_WRITE_TEMPLATE.format(branch)]),
      api.post_process(post_process.StepCommandContains,
                       'update config.write release/release_builders.textpb',
                       [EXPECTED_WRITE_TEMPLATE % (branch_milestone, branch)]))

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
  )

  yield api.test(
      'prune',
      api.properties(
          **{
              'release_branch':
                  branch,
              '$chromeos/cros_release_config':
                  CrosReleaseConfigProperties(auto_submit=True,
                                              keep_n_milestones=3),
          }),
      api.post_process(
          post_process.StepCommandContains,
          'update config.write release/release_builders.textpb',
          [EXPECTED_WRITE_PRUNED_TEMPLATE % (branch_milestone, branch)]))
