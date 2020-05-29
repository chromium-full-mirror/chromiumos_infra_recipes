# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'cros_infra_config',
    'metadata_json',
]

from collections import namedtuple
from google.protobuf import struct_pb2
from PB.chromiumos.common import BuildTarget


def RunSteps(api):
  api.metadata_json.add_default_entries()
  config = api.cros_infra_config.get_builder_config('amd64-generic-cq')
  bt = BuildTarget(name='amd64-generic')
  api.metadata_json.upload_to_gs(config, bt, partial=True)


def GenTests(api):
  md_build = api.buildbucket.try_build_message(bucket='cq',
                                               builder='amd64-generic-cq')
  yield api.test(
      'basic', api.buildbucket.simulated_get(md_build, 'buildbucket.get'),
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='amd64-generic-cq'))
