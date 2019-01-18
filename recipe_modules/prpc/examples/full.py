# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'prpc',
]


def RunSteps(api):
  msg_type = api.buildbucket.build_pb2.Build
  msg = msg_type()
  msg.id = 12345
  api.prpc.call_proto('prpc.example.com', 'my.pkg.Method', msg, msg_type,
                      test_output_msg=msg)


def GenTests(api):
  yield api.test('basic')
