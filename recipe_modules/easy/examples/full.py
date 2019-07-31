# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/json',
    'recipe_engine/raw_io',
    'easy',
]

from google.protobuf.wrappers_pb2 import Int32Value

def RunSteps(api):
  api.easy.step('passthru', ['cat'], ok_ret=(0, 1))

  stdout = api.easy.stdout_step('raw', ['gzip'], stdin_data='uncompressed',
                                   test_stdout=lambda: 'compressed')
  assert stdout == 'compressed'

  proto_out = api.easy.stdout_jsonpb_step('jsonpb', ['foo'], Int32Value,
      test_output=Int32Value(value=1))
  assert isinstance(proto_out, Int32Value)
  assert proto_out.value == 1

  json_stdout = api.easy.stdout_json_step('json', ['jq'], stdin_json={'a': 1},
                                   test_stdout={'b': 2})
  assert json_stdout == {'b': 2}
  api.easy.set_property_step('property', 'value')


def GenTests(api):
  yield api.test('basic')
