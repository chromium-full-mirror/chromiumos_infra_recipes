# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'ipc'
]

def RunSteps(api):
  api.ipc.send('topic', '/path/to/message/file',
               {"foo": "bar", "baz": "quux"})
  api.ipc.receive('topic', 'subscription name',
                  {"foo": "bar", "baz": "quux"})

def GenTests(api):
  yield api.test('basic')
