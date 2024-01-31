# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import PB.chromiumos.common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'cros_release_util',
]



def RunSteps(api):
  api.assertions.assertEqual(
      api.cros_release_util.channel_strip_prefix(
          common_pb2.Channel.CHANNEL_BETA), 'beta')
  api.assertions.assertEqual(
      api.cros_release_util.channel_to_long_string(
          common_pb2.Channel.CHANNEL_BETA), 'beta-channel')
  api.assertions.assertEqual(
      api.cros_release_util.channel_long_string_to_enum('beta-channel'),
      common_pb2.Channel.CHANNEL_BETA)
  api.assertions.assertEqual(
      api.cros_release_util.channel_short_string_to_enum('beta'),
      common_pb2.Channel.CHANNEL_BETA)


def GenTests(api):
  yield api.test('basic')
