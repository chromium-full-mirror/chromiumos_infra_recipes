# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


DEPS = [
  'build_api',
]


class MockProto(object):
  def SerializeToString(self):
    return 'FAKE JSON'

  @classmethod
  def FromString(cls, _):
    return None

def RunSteps(api):
  api.build_api._call('chromite.api.group', MockProto(), MockProto)

def GenTests(api):
  yield api.test('basic')
