# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import BuildTarget

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_infra_config',
    'metadata_json',
]



def RunSteps(api):
  config = api.cros_infra_config.config
  bt = BuildTarget(name='amd64-generic')
  with api.metadata_json.context(config, [bt]):
    api.metadata_json.add_default_entries()
    raise api.step.StepFailure('something went wrong.')


def GenTests(api):
  yield api.test(
      'basic',
      api.metadata_json.test_builder('amd64-generic', cq=True),
      status='FAILURE',
  )
