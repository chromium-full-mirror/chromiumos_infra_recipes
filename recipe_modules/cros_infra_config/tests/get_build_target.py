# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def RunSteps(api):
  api.assertions.assertIsNone(
      api.cros_infra_config.get_build_target_name(build_pb2.Build()))
  api.assertions.assertIsNone(api.cros_infra_config.get_build_target_name())


def GenTests(api):

  yield api.test('basic')
