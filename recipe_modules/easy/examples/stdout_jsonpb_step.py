# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'easy',
]

from google.protobuf.wrappers_pb2 import Int32Value

def RunSteps(api):
  out = api.easy.stdout_jsonpb_step('foo', ['foo'], Int32Value)
  assert out.value == 1


def GenTests(api):
  yield (api.test('basic') +  #
         api.easy.simulate_jsonpb_step('foo', Int32Value(value=1)))
