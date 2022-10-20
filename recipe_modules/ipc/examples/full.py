# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['ipc']

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.ipc.send('topic', '/path/to/message/file', {"foo": "bar", "baz": "quux"})
  api.ipc.receive('topic', 'subscription name', {"foo": "bar", "baz": "quux"})
  api.ipc.make_subscription('topic', 'subscription')


def GenTests(api):
  yield api.test('basic')
