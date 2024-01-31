# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import itertools

import PB.chromiumos.common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'cros_release_util',
]



def RunSteps(api):
  dev_short = 'dev'
  dev_long = 'dev-channel'
  dev_enum = common_pb2.Channel.CHANNEL_DEV
  dev_channels = (dev_short, dev_long, dev_enum)

  canary_short = 'canary'
  canary_long = 'canary-channel'
  canary_enum = common_pb2.Channel.CHANNEL_CANARY
  canary_channels = (canary_short, canary_long, canary_enum)

  for (dev1, dev2) in itertools.product(dev_channels, dev_channels):
    api.assertions.assertTrue(api.cros_release_util.match_channels(dev1, dev2))

  for (can1, can2) in itertools.product(canary_channels, canary_channels):
    api.assertions.assertTrue(api.cros_release_util.match_channels(can1, can2))

  for (dev, can) in itertools.product(dev_channels, canary_channels):
    api.assertions.assertFalse(api.cros_release_util.match_channels(dev, can))

  # Channel enum is technically just integers, so this works:
  api.assertions.assertTrue(api.cros_release_util.match_channels(3, 3))
  api.assertions.assertTrue(api.cros_release_util.match_channels(3, dev_short))
  # But not all integers are valid Channels:
  with api.assertions.assertRaises(Exception):
    api.assertions.assertTrue(api.cros_release_util.match_channels(1000, 1000))


def GenTests(api):
  yield api.test('basic')
