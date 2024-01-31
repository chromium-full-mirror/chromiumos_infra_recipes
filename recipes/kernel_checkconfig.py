# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing the kernel splitconfig normalization.

The kernel split config design is documented at
https://www.chromium.org/chromium-os/how-tos-and-troubleshooting/kernel-configuration/
and go/mini-splitconfigs.
"""

from PB.recipes.chromeos.kernel_checkconfig import KernelCheckconfigProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
]


PROPERTIES = KernelCheckconfigProperties


def RunSteps(api: RecipeApi, properties: KernelCheckconfigProperties):
  with api.step.nest('validate properties') as presentation:
    if not properties.source_path:
      raise StepFailure('must set source_path')

    presentation.step_text = 'all properties good'

  with api.build_menu.configure_builder(missing_ok=True), \
    api.build_menu.setup_workspace_and_chroot():

    api.cros_source.ensure_synced_cache()
    api.cros_sdk('kernelconfig checkconfig', [
        '--working-dir', properties.source_path, '--log-level',
        api.cros_build_api.log_level, '--', './chromeos/scripts/kernelconfig',
        'checkconfig'
    ])


def GenTests(api: RecipeTestApi):
  props = {
      'source_path': 'src/third_party/kernel/v5.15',
  }
  yield api.test(
      'basic',
      api.properties(**props),
      api.post_check(post_process.MustRun, 'kernelconfig checkconfig'),
  )

  props = {}
  yield api.test(
      'no_source_path',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'kernelconfig checkconfig'),
      status='FAILURE',
  )
