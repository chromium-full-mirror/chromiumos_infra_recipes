# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.sysroot_util.examples.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/json',
    'cros_infra_config',
    'sysroot_util',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  name = properties.builder_name or 'snapshot-orchestrator'

  _ = api.cros_infra_config.get_builder_config(name)

  sysroot = api.sysroot_util.create_sysroot(
      BuildTarget(name='eve'), use_cq_prebuilts=properties.use_cq_prebuilts)
  api.assertions.assertEqual(sysroot, api.sysroot_util.sysroot)

  api.sysroot_util.bootstrap_sysroot()


def GenTests(api):
  yield api.test(
      'basic',
      # "useCqPrebuilts" should not exist or be false by default.
      api.post_check(lambda check, steps: check(not api.json.loads(steps[
          'create sysroot.call chromite.api.SysrootService/Create'].logs[
              'request'])['flags'].get('useCqPrebuilts', False))),
  )

  yield api.test(
      'use-cq-prebuilts',
      api.properties(TestInputProperties(use_cq_prebuilts=True)),
      # "useCqPrebuilts" should be true.
      api.post_check(lambda check, steps: check(
          api.json.loads(steps[
              'create sysroot.call chromite.api.SysrootService/Create'].logs[
                  'request'])['flags'].get('useCqPrebuilts', False))),
  )
