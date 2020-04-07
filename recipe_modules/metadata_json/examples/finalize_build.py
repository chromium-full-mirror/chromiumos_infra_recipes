# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
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
  api.metadata_json.finalize_build('bucket', config, bt, True)
  metadata = api.metadata_json.get_metadata()
  api.assertions.assertEqual(len(metadata['status']), 3)


def GenTests(api):
  yield (api.test('basic') + api.buildbucket.ci_build(
      project='chromeos', bucket='cq', builder='amd64-generic-cq'))
