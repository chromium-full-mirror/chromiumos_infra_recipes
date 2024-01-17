# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running Kabuto's export_dlc_info script."""

from PB.recipes.chromeos.kabuto_export_dlc_info import (
    KabutoExportDlcInfoProperties)
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'git',
]

PROPERTIES = KabutoExportDlcInfoProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi, properties: KabutoExportDlcInfoProperties) -> None:
  borealis_checkout = api.path.mkdtemp('borealis')
  with api.context(cwd=borealis_checkout):
    with api.step.nest('clone kabuto'):
      # Clone Borealis, Kabuto is in borealis/tools/kabuto.
      remote = 'https://chrome-internal.googlesource.com/chromeos/platform/borealis'
      api.git.clone(remote)

    # path to export_dlc_info script.
    export_cmd = [
        './tools/kabuto_production_utils/export_dlc_info/export_dlc_info.sh'
    ]

    # Add optional arguments if specified in job properties.
    if properties.major_version_backtrack_count:
      export_cmd.append('--major-version-backtrack-count')
      export_cmd.append(properties.major_version_backtrack_count)

    mesa_dir = api.path.mkdtemp('mesa')
    export_cmd.append('--mesa-version-hash-tmp-dir')
    export_cmd.append(mesa_dir)

    ebuild_log_dir = api.path.mkdtemp('ebuild')
    export_cmd.append('--ebuild-log-tmp-dir')
    export_cmd.append(ebuild_log_dir)

    # Run export_dlc_info.
    api.step('run export_dlc_info', export_cmd)


def GenTests(api: RecipeTestApi) -> None:
  good_props = {}
  yield api.test(
      'basic',
      api.properties(**good_props),
  )

  props = good_props.copy()
  props['major_version_backtrack_count'] = 4
  yield api.test(
      'major-version-backtrack-count',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains,
          'run export_dlc_info',
          [
              './tools/kabuto_production_utils/export_dlc_info/export_dlc_info.sh',
              '--major-version-backtrack-count', '4',
              '--mesa-version-hash-tmp-dir', '[CLEANUP]/mesa_tmp_1',
              '--ebuild-log-tmp-dir', '[CLEANUP]/ebuild_tmp_1'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
