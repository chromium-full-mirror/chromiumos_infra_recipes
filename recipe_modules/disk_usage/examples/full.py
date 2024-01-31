# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'disk_usage',
]



def RunSteps(api):
  with api.disk_usage.tracking_context():
    api.disk_usage.track(depth=1, d='/')


def GenTests(api):
  yield api.test('basic')
