# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cros_infra_config',
    'metadata_json',
]

from collections import namedtuple
from google.protobuf import struct_pb2
from PB.chromiumos.common import BuildTarget


def RunSteps(api):
  config = api.cros_infra_config.get_builder_config('amd64-generic-cq')
  bt = BuildTarget(name='amd64-generic')
  with api.metadata_json.context(config, bt):
    api.metadata_json.add_default_entries()
    raise api.step.StepFailure('something went wrong.')


def GenTests(api):
  md_build = api.buildbucket.try_build_message(bucket='cq',
                                               builder='amd64-generic-cq')
  yield (api.test('basic') +  #
         api.buildbucket.simulated_get(md_build,
                                       'metadata setup.buildbucket.get') +  #
         api.buildbucket.simulated_get(md_build, 'buildbucket.get') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='cq',
                                  builder='amd64-generic-cq'))
