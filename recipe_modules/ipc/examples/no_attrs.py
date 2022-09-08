# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['ipc']

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.ipc.send('topic', '/path/to/message/file')
  api.ipc.receive('topic', 'subscription name')


def GenTests(api):
  yield api.test('basic')
