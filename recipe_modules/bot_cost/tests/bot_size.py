# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_cost',
    'cros_tags',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


def RunSteps(api):
  api.assertions.assertEqual(api.bot_cost._machine_type, None)
  api.assertions.assertRaises(ValueError, api.bot_cost.set_build_cost)


def GenTests(api):

  def test(name, status, machine_type):
    bld_msg = build_pb2.Build(id=123, status=status)
    bld_msg.infra.swarming.bot_dimensions.extend(
        api.cros_tags.tags(machine_type=machine_type))
    return api.test(name, api.buildbucket.build(bld_msg))

  yield test('bad-size', status='STARTED', machine_type='bad')
